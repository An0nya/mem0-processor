// claude-code-mem0-uploader.mjs (v7.2)
//
// Summarizes Claude Code session logs via a local or cloud LLM,
// then uploads to Mem0 under a flat user_id namespace.
//
// KEY DESIGN DECISIONS:
//   - All memories go to user_id="summary-sessions" with NO run_id or agent_id.
//   - infer=false (default): summaries stored as single blobs. Inference layer
//     was producing hallucinated memories from adjacent context.
//   - POST /v1/memories/ is the correct add endpoint.
//   - Per-model state files are intentional — same sessions can be run
//     through multiple models for benchmarking without collision.
//   - LM Studio v0 API used at startup to get loaded model + context length.
//     loaded_context_length reflects the actual loaded window, not model max.
//     Falls back to CONFIG.maxTranscriptChars when no LM Studio info is available.
//     If --model not given, defaults to whatever is currently loaded in LM Studio.
//   - tps, ttft, prefillTps, promptTokens pulled from LM Studio v0 response stats.
//   - GPU-wired RAM sampled via ioreg AGXAccelerator during summarization (peak + avg).
//   - Swap sampled via sysctl vm.swapusage; memory pressure via memory_pressure CLI.
//   - Runs are logged to ~/.claude/mem0/logs/ as JSONL.
//
// CONTEXT CAP:
//   - Hard script ceiling: CONTEXT_CAP = 64k tokens * 3.5 chars/token.
//   - Intersected with model's loaded_context_length * 3.5. Lower value wins.
//   - Transcripts exceeding the cap are skipped (not truncated).
//   - --no-token-cap bypasses the script ceiling only; model context is still the limit.
//   - v8 will replace the hard ceiling with a per-model regression fit derived
//     from perf store data (see TODO near CONTEXT_CAP definition).
//
// PERF STORE:
//   - ~/.claude/mem0/perf.json. One entry per session summarization, append-only.
//   - Fields: idleGb, preSessionIdleGb, peakGb, avgGb, tps, prefillTps, ttft,
//     genTime, promptTokens, reasoningTokens, completionTokens, transcriptChars,
//     loadedContextChars, startingSwap, maxSwap, peakPressure, pressureAvg.
//   - Models in the perf store are auto-merged into MODELS at startup.
//
// KNOWN BUGS:
//   - Script hangs after printing final stats instead of exiting cleanly.
//     Likely an open handle (LM Studio or mem0 HTTP keep-alive, or pending
//     async timer). Mitigated: process.exit(0) appended to main() call.
//     Root cause not yet identified — if this script is ever run in a test
//     harness or daemonized, audit which client is leaving handles open.
//   - BUG: model default was hardcoded MODELS[0] (gemma) even when a
//     different model was loaded in LM Studio. listLoadedModels() existed
//     in v5 but was never called from selectModel(). Fixed: --model-less
//     runs now query /api/v0/models?state=loaded and use the first result,
//     matched against MODELS for provider info (defaults to lmstudio if
//     unknown). State file and summary cache will now be named after the
//     actual running model instead of silently defaulting to gemma.
import fs from "fs";
import path from "path";
import os from "os";
import { exec, execSync } from "child_process";
import Anthropic from "@anthropic-ai/sdk";
import { setGlobalDispatcher, Agent } from 'undici';


// ─── MODEL REGISTRY ──────────────────────────────────────────────
const MODELS = [
  { id: "google/gemma-3-12b",                              provider: "lmstudio" },
  { id: "qwen3.5-9b-optiq",                                provider: "lmstudio" },
  { id: "qwen/qwen3-14b",                                  provider: "lmstudio" },
  { id: "gpt-oss-20b-mlx",                                 provider: "lmstudio" },
  { id: "qwen/qwen3-4b-2507",                              provider: "lmstudio" },
  { id: "qwen/qwen3-4b-thinking-2507",                     provider: "lmstudio" },
  { id: "microsoft/phi-4-reasoning-plus",                  provider: "lmstudio" },
  { id: "mistralai_ministral-3-14b-instruct-2512-mlx",     provider: "lmstudio" },
  { id: "meta-llama-3.1-8b-instruct",                      provider: "lmstudio" },
  { id: "qwen/qwen3-8b",                    		   provider: "lmstudio" },
  { id: "claude-haiku-4-5-20251001",                       provider: "anthropic" },
];

// ─── CONFIG ──────────────────────────────────────────────────────
const LMSTUDIO_ENDPOINT = "http://localhost:1234";

//This may be a fix for the fetch failed timeout error
setGlobalDispatcher(new Agent({
  headersTimeout: 30 * 60 * 1000,
  bodyTimeout:    30 * 60 * 1000,
  connectTimeout: 30 * 1000,
}));

const CONFIG = {
  mem0: {
    apiKey: process.env.MEM0_API_KEY,
    userId: "summary-sessions",
  },
  //sorry, changed this without mentioning, infer true was useless. I did think we had discussed this already by maybe not
  infer: "false",
  toolResultMaxChars: 1000,
  maxTranscriptChars: 224000,
};

const PROJECTS_DIR    = path.join(os.homedir(), ".claude", "projects");
const MEM0_DIR        = path.join(os.homedir(), ".claude", "mem0");
const SUMMARIES_DIR   = path.join(MEM0_DIR, "summaries");
const ARCHIVE_DIR     = path.join(SUMMARIES_DIR, "archive");
const LOGS_DIR        = path.join(MEM0_DIR, "logs");
const PERF_STORE_PATH = path.join(MEM0_DIR, "perf.json");

const DRY_RUN        = process.argv.includes("--dry-run");
const NO_TOKEN_CAP = process.argv.includes("--no-token-cap");
const STREAM         = process.argv.includes("--stream");
const NO_UPLOAD      = process.argv.includes("--no-upload");
const REPROCESS_ID   = (() => {
  const i = process.argv.indexOf("--reprocess");
  if (i === -1) return null;
  const next = process.argv[i + 1];
  return (!next || next.startsWith("--")) ? "all" : next;
})();

// ─── PERF STORE ──────────────────────────────────────────────────
function loadPerfStore() {
  if (!fs.existsSync(PERF_STORE_PATH)) return {};
  return JSON.parse(fs.readFileSync(PERF_STORE_PATH, "utf8"));
}

function savePerfStore(store) {
  fs.mkdirSync(path.dirname(PERF_STORE_PATH), { recursive: true });
  fs.writeFileSync(PERF_STORE_PATH, JSON.stringify(store, null, 2));
}

function appendPerfEntry(store, modelId, entry) {
  if (!store[modelId]) store[modelId] = { runs: [] };
  store[modelId].runs.push(entry);
  savePerfStore(store);
}

// TODO v8: replace CONTEXT_CAP hard ceiling with per-model regression fit
// (largest transcriptChars where peakPressure + swap stay under threshold).
// getModelMaxPeak / getModelFailCap removed — superseded by this plan.

// ─── MODEL SELECTION ─────────────────────────────────────────────
async function selectModel() {
  const flag = process.argv.indexOf("--model");
  if (flag !== -1 && process.argv[flag + 1]) {
    const query = process.argv[flag + 1].toLowerCase();
    const match = MODELS.find((m) => m.id.toLowerCase().includes(query));
    if (!match) {
      console.error(
        `No model matching "${query}" in registry. Available:\n${MODELS.map((m) => `  ${m.id}`).join("\n")}`
      );
      process.exit(1);
    }
    return match;
  }

  // FIX (v6): actually call the loaded-models endpoint instead of hardcoding MODELS[0].
  try {
    const res = await fetch(`${LMSTUDIO_ENDPOINT}/api/v0/models?state=loaded`);
    if (res.ok) {
      const data = await res.json();
      const loaded = data.data || [];
      if (loaded.length > 0) {
        const loadedId = loaded[0].id;
        const registered = MODELS.find((m) => m.id === loadedId);
        const model = registered ?? { id: loadedId, provider: "lmstudio" };
        if (!registered) {
          console.warn(`  ⚠ "${loadedId}" not in registry — assuming lmstudio provider. Add it to MODELS if you plan to run it regularly.`);
        }
        console.log(`Auto-detected loaded model: ${model.id}`);
        return model;
      }
      console.warn("⚠ LM Studio reports no models currently loaded");
    }
  } catch {
    // LM Studio not running or v0 unavailable
  }

  console.error("✗ No model loaded in LM Studio and no --model flag given. Load a model or pass --model <id>.");
  process.exit(1);
}

// ─── STATE TRACKING (per-model) ──────────────────────────────────
function stateFilePath(modelId) {
  const slug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return path.join(MEM0_DIR, "state", `${slug}.json`);
}

function loadState(modelId) {
  const p = stateFilePath(modelId);
  if (!fs.existsSync(p)) return {};
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function saveState(state, modelId) {
  const p = stateFilePath(modelId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(state, null, 2));
}

// ─── SUMMARY CACHE ───────────────────────────────────────────────
function summaryPath(sessionId, modelId) {
  fs.mkdirSync(SUMMARIES_DIR, { recursive: true });
  const slug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return path.join(SUMMARIES_DIR, `${sessionId}--${slug}.txt`);
}

function loadCachedSummary(sessionId, modelId) {
  const p = summaryPath(sessionId, modelId);
  if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
  return null;
}

function saveCachedSummary(sessionId, modelId, summary, archive = false) {
  const p = summaryPath(sessionId, modelId);
  if (archive && fs.existsSync(p)) {
    const slug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
    const archiveDir = path.join(ARCHIVE_DIR, slug);
    fs.mkdirSync(archiveDir, { recursive: true });
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    fs.renameSync(p, path.join(archiveDir, `${sessionId}--${ts}.txt`));
  }
  fs.writeFileSync(p, summary);
}

// ─── LM STUDIO v0 API ────────────────────────────────────────────
async function getModelInfo(modelId) {
  try {
    const res = await fetch(`${LMSTUDIO_ENDPOINT}/api/v0/models/${encodeURIComponent(modelId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ─── SESSION DISCOVERY ───────────────────────────────────────────
function findSessions() {
  const sessions = [];
  if (!fs.existsSync(PROJECTS_DIR)) return sessions;
  for (const projectDir of fs.readdirSync(PROJECTS_DIR)) {
    const projectPath = path.join(PROJECTS_DIR, projectDir);
    if (!fs.statSync(projectPath).isDirectory()) continue;
    for (const file of fs.readdirSync(projectPath)) {
      if (!file.endsWith(".jsonl")) continue;
      sessions.push({
        sessionId: path.basename(file, ".jsonl"),
        projectDir,
        filePath: path.join(projectPath, file),
      });
    }
  }
  return sessions;
}

// ─── JSONL PARSING ───────────────────────────────────────────────
function parseSession(filePath) {
  return fs
    .readFileSync(filePath, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean);
}

// ─── CONTENT EXTRACTION ─────────────────────────────────────────
function extractContentBlocks(entry) {
  if (entry.message?.content) {
    return { blocks: entry.message.content, entryType: entry.type, model: entry.message?.model || null };
  }
  if (entry.data?.message?.message?.content) {
    return {
      blocks: entry.data.message.message.content,
      entryType: entry.data.message.type,
      model: entry.data.message.message.model || "unknown",
    };
  }
  return null;
}

// ─── TRANSCRIPT BUILDING ────────────────────────────────────────
function buildTranscript(entries) {
  const lines = [];
  const cap = CONFIG.toolResultMaxChars;

  for (const entry of entries) {
    const extracted = extractContentBlocks(entry);
    if (!extracted) continue;
    const { blocks, entryType, model } = extracted;
    const isSubAgent = !!entry.data?.message?.message;
    const agentTag = isSubAgent ? ` (sub-agent: ${model})` : "";

    for (const block of blocks) {
      if (block.type === "thinking") continue;
      if (block.type === "text") {
        lines.push(`[${entryType === "user" ? "USER" : "ASSISTANT"}${agentTag}] ${block.text}`);
      } else if (block.type === "tool_use") {
        lines.push(`[TOOL_CALL${agentTag}] ${block.name}(${JSON.stringify(block.input).slice(0, 300)})`);
      } else if (block.type === "tool_result") {
        const raw = typeof block.content === "string" ? block.content : JSON.stringify(block.content);
        if (raw.includes("<persisted-output>")) {
          const sizeMatch = raw.match(/Output too large \([\d.]+KB\)/);
          lines.push(`[TOOL_RESULT${agentTag}] ${sizeMatch?.[0] || "Large output"} — persisted to disk`);
        } else {
          lines.push(`[${block.is_error ? "TOOL_ERROR" : "TOOL_RESULT"}${agentTag}] ${raw.slice(0, cap)}`);
        }
      }
    }
  }

  return lines.join("\n");
}

// ─── RAM SAMPLING ────────────────────────────────────────────────
// On Apple Silicon, MLX model weights are mmap'd and wired by the GPU driver —
// invisible to ps rss, which only counts CPU-faulted pages. ioreg reads the
// AGX/Metal layer directly and exposes "Alloc system memory from IOKit",
// which is the total GPU-wired allocation (weights + KV cache). No sudo needed.
// This is what tools like gpuer and asitop use under the hood.
function gpuAllocGb() {
  try {
    const raw = execSync("ioreg -r -c AGXAccelerator -d 2", { encoding: "utf8" });
    const match = raw.match(/"Alloc system memory"=(\d+)/);
    if (!match) return null;
    return +(parseInt(match[1], 10) / 1e9).toFixed(2);
  } catch {
    return null;
  }
}

function swapUsedGb() {
  try {
    const raw = execSync("sysctl vm.swapusage", { encoding: "utf8" });
    const match = raw.match(/used\s*=\s*([\d.]+)([KMG])/);
    if (!match) return null;
    const val = parseFloat(match[1]);
    const unit = match[2];
    return +(val / (unit === "G" ? 1 : unit === "M" ? 1024 : 1048576)).toFixed(3);
  } catch { return null; }
}

function memPressureLevel() {
  try {
    const raw = execSync("memory_pressure", { encoding: "utf8" });
    const match = raw.match(/System-wide memory free percentage:\s*(\d+)%/);
    if (!match) return null;
    return 100 - parseInt(match[1], 10);
  } catch { return null; }
}

function startRamSampler(intervalMs = 500) {
  const allocRamSamples = [];
  const swapSamples = [];
  const pressureSamples = [];
  const interval = setInterval(() => {
    const gb = gpuAllocGb();
    if (gb !== null) allocRamSamples.push(gb);
    const swap = swapUsedGb();
    if (swap !== null) swapSamples.push(swap);
    const pressure = memPressureLevel();
    if (pressure !== null) pressureSamples.push(pressure);
  }, intervalMs);
  return {
    stop() {
      clearInterval(interval);
      if (allocRamSamples.length === 0) return { peakUsedGb: null, avgUsedGb: null };
      const allocPeak = Math.max(...allocRamSamples);
      const allocAvg  = allocRamSamples.reduce((a, b) => a + b, 0) / allocRamSamples.length;
      const startingSwap = Math.min(...swapSamples);
      const swapMax = Math.max(...swapSamples);
      const pressurePeak = Math.max(...pressureSamples);
      const pressureAvg = pressureSamples.reduce((a, b) => a + b, 0) / pressureSamples.length;
      return {
        peakUsedGb: +allocPeak.toFixed(2),
        avgUsedGb:  +allocAvg.toFixed(2),
        startingSwap: +startingSwap.toFixed(2),
        maxSwap: +swapMax.toFixed(2),
        peakPressure: +pressurePeak,
        pressureAvg: +pressureAvg.toFixed(2)
      };
    },
  };
}

// ─── SUMMARIZATION PROMPT ────────────────────────────────────────
const SUMMARIZATION_PROMPT = `
Write a standalone analytical summary of this Claude Code session.
\"Standalone\" means readable cold with no transcript access.
Output the document only — no preamble, reasoning trace, or meta-commentary.

This summary helps the user learn where they trusted Claude too much,
where Claude acted faster than it should have, and where context or
time was wasted. Catching code bugs is secondary to surfacing these
trust-calibration and efficiency signals.

## Goal
What the user was actually trying to accomplish. Infer the real
objective from opening context, not the first concrete request.
1–3 sentences.

## What Happened & Why
Narrative, not a log. What drove each major turn? What assumptions
were active? Where did plans change, and why? Do not enumerate tool
calls. If the session wandered, re-did work, or pivoted mid-task,
say so plainly.

## Competence & Clarifications
Two things, distinctly:
- What the user independently knew, caught, or identified.
- What the user asked Claude to explain or justify. Clarifying
  questions (\"wtf is that syntax,\" \"is that timezone-safe\") are
  competence signals about how the user is thinking — not mistakes —
  even when Claude's answer is correct and no change results.
Note gaps: places the user deferred without understanding.

## Mistakes & Overreach
Label each item as ERROR or OVERREACH.
- ERROR: something wrong was produced. Record who made it, how it
  was caught, and whether any process (test, validation, obvious
  failure) would have caught it — or whether it was caught only
  because someone happened to look. Flag luck-catches explicitly.
- OVERREACH: Claude took an action without pausing when it should
  have asked — running tools, editing files, picking an approach —
  even if the result was fine. Also include cases where Claude
  answered from assumption rather than reading available context.

## Friction Points
Rejected edits, interruptions, re-reads. For each, say which bucket:
genuine catch, user confusion or caution, or Claude moving too fast.
These are primary signals — do not omit them even if they resolved
cleanly.

## Waste & Efficiency
Where context, tokens, or time got burned unnecessarily. Examples:
Claude reading files it didn't need, running bash before asking
where a file lived, re-doing work because it skipped reading an
existing file, pulling large tool output that didn't inform the
next step. Brief — one paragraph or a short list.

## Decisions (attributed)
[USER]              independently proposed or diagnosed
[USER-APPROVED]     user said okay/sure without engaging
[USER-CLARIFIED]    user asked, Claude explained correctly, user
                    accepted — no change needed
[CLAUDE]            Claude produced this; user may not have verified
[CLAUDE-UNPROMPTED] Claude did this without being asked, in a spot
                    where asking first would have been appropriate

Flag where confident framing by either party masked a wrong
assumption or unclear scope.

## Open Threads
Unfinished work. Concrete enough to act on.

Rules: expand acronyms on first use. Sub-agent calls count as
Claude's work. When uncertain who proposed something, default to
[CLAUDE].
`.trim();

// ─── SUMMARIZATION ───────────────────────────────────────────────
const anthropic = new Anthropic();

async function summarizeSession(transcript, model) {
  if (model.provider === "anthropic") {
    //upped response limit to avoid truncation and reasoning model failure
    const response = await anthropic.messages.create({
      model: model.id,
      max_tokens: 2048,
      system: SUMMARIZATION_PROMPT,
      messages: [{ role: "user", content: transcript }],
    });
    return { summary: response.content[0].text, tps: null, completionTokens: response.usage.output_tokens };
  }

  if (model.provider === "lmstudio") {
    // FIX (v6): was /v1/chat/completions — that endpoint does NOT populate
    // data.stats.tokens_per_second. The v0 endpoint does. This is why tps
    // was always n/a in v5 despite the stats-parsing code being correct.
    //
    let response;
    try {
      response = await fetch(`${LMSTUDIO_ENDPOINT}/api/v0/chat/completions`, {
      method: "POST",
      signal: AbortSignal.timeout(30 * 60 * 1000), // 30 minutes
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.id,
        messages: [
          { role: "system", content: SUMMARIZATION_PROMPT },
          { role: "user",   content: transcript },
        ],
        max_tokens: 8182,
        stream: STREAM,
      }),
    });
    } catch (fetchErr) {
      throw new Error(`LM Studio fetch failed (${transcript.length} chars): ${fetchErr.message}`);
    }

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`LM Studio ${response.status} (${transcript.length} chars): ${body.slice(0, 300)}`);
    }

    if (STREAM) {
      let summary = "";
      let tps = null;
      let completionTokens = null;
      process.stdout.write("  ");
      for await (const chunk of response.body) {
        for (const line of Buffer.from(chunk).toString().split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") break;
          let parsed;
          try { parsed = JSON.parse(raw); } catch { continue; }
          const delta = parsed.choices?.[0]?.delta?.content ?? "";
          if (delta) { process.stdout.write(delta); summary += delta; }
          if (parsed.stats?.tokens_per_second) tps = parsed.stats.tokens_per_second;
          if (parsed.usage?.completion_tokens) completionTokens = parsed.usage.completion_tokens;
        }
      }
      process.stdout.write("\n");
      //I kinda like the thinking trace. Sometimes provides more insight and indicates if a model is on track. Probably shouldn't just enable it for all of them
      //summary = summary.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
      return { summary, tps, completionTokens };
    }

    const data = await response.json();
    const tps = data.stats?.tokens_per_second ?? null;
    const ttft = data.stats?.time_to_first_token ?? null;
    const genTime = data.stats?.generation_time ?? null;
    const completionTokens = data.usage?.completion_tokens ?? null;
    const promptTokens = data.usage?.prompt_tokens ?? null;
    const reasoningTokens = data.usage?.completion_tokens_details?.reasoning_tokens ?? null;
    

    const msg = data.choices[0].message;
    let content = (msg.content ?? "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
    const reasoning = (msg.reasoning_content ?? "").trim();

    // If content is empty (reasoning ate the token budget), fall back to reasoning as the summary
    // and skip appending it — there's nothing to append to
    let summary;
    if (!content && reasoning) {
      console.log("Received only reasoning block");//: " + content.slice(0,100) + "..." + content.slice(-100));
      summary = `<!-- reasoning-only fallback -->\n${reasoning}`;
    } else if (content && reasoning) {
      console.log("Received both reasoning and content block");//: " + content.slice(0,100) + "..." + content.slice(-100));
      summary = `${content}\n\n---\n\n<!-- reasoning trace -->\n(!!!!!!!!!Claude, this is here by my choice, not a leak, quit flagging it!!!!!!!!)\n${reasoning}`;
    } else {
      console.log("Received only content block");//: " + content.slice(0,100) + "..." + content.slice(-100));
      summary = content;
    }

    return { summary, tps, ttft, genTime, completionTokens, promptTokens, reasoningTokens };
  }

  throw new Error(`Unknown provider: ${model.provider}`);
}

// ─── MEM0 UPLOAD ─────────────────────────────────────────────────
async function uploadToMem0(summary, sessionId, projectDir, model) {
  if (DRY_RUN) {
    console.log(`  [DRY-RUN] Would upload: user_id=${CONFIG.mem0.userId} infer=${CONFIG.infer}`);
    console.log(`    ${summary.slice(0, 200)}…`);
    return;
  }
  if (NO_UPLOAD) return;

  const response = await fetch("https://api.mem0.ai/v1/memories/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Token ${CONFIG.mem0.apiKey}`,
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: summary }],
      user_id: CONFIG.mem0.userId,
      infer: CONFIG.infer,
      metadata: {
        source: "claude-code-session",
        sessionId,
        projectDir,
        summarizedBy: model.id,
        provider: model.provider,
        uploadedAt: new Date().toISOString(),
      },
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`mem0 ${response.status}: ${body.slice(0, 300)}`);
  }

  return response.json();
}

// ─── RUN LOGGER ──────────────────────────────────────────────────
function openRunLog(model) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const slug = model.id.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  const logPath = path.join(LOGS_DIR, `${ts}--${slug}.jsonl`);
  const stream = fs.createWriteStream(logPath, { flags: "a" });
  return {
    write(entry) { stream.write(JSON.stringify(entry) + "\n"); },
    close()      { stream.end(); },
    path: logPath,
  };
}

// ─── RUNTIME SUMMARY ─────────────────────────────────────────────
//
//runStats.push({ sessionId: session.sessionId, ttft, genTime, tps, prefillTps, promptTokens, completionTokens, inputChars, peakUsedGb, avgUsedGb, startingSwap, maxSwap, peakPressure, pressureAvg });
//
function printSummary(model, modelInfo, stats) {
  const ttftSamples = stats.filter((s) => s.ttft != null).map((s) => s.ttft);
  const genTimeSamples = stats.filter((s) => s.genTime != null).map((s) => s.genTime);

  const tpsSamples = stats.filter((s) => s.tps != null).map((s) => s.tps);
  const prefillSamples = stats
  .filter((s) => s.prefillTps != null)
  .map((s) => parseFloat(s.prefillTps));  const ramSamples = stats.filter((s) => s.peakUsedGb != null);
  const swapSamples = stats.filter((s) => s.maxSwap != null);
  const pressureSamples = stats.filter((s) => s.peakPressure != null);

  const totalPrefillTime = ttftSamples.reduce((a, s) => a + s, 0);
  const totalGenTime = genTimeSamples.reduce((a, s) => a + s, 0);
  const totalRuntime = totalPrefillTime + totalGenTime;

  const avgTps  = tpsSamples.length ? (tpsSamples.reduce((a, b) => a + b, 0) / tpsSamples.length).toFixed(1) : "n/a";
  const peakTps = tpsSamples.length ? Math.max(...tpsSamples).toFixed(1) : "n/a";
  const minTps  = tpsSamples.length ? Math.min(...tpsSamples).toFixed(1) : "n/a";
  //fix prefill (NaN in summary...?)fixed?
  //console.log(`prefill samples: ${prefillSamples}, prefill samples sum: ${prefillSamples.reduce((a, b) => a + b, 0)}, prefill samples length: ${prefillSamples.length}`);
  const avgPrefill = prefillSamples.length ? (prefillSamples.reduce((a, b) => a + b, 0) / prefillSamples.length).toFixed(1) : "n/a";
  const peakPrefill = prefillSamples.length ? Math.max(...prefillSamples).toFixed(1) : "n/a";
  const minPrefill  = prefillSamples.length ? Math.min(...prefillSamples).toFixed(1) : "n/a";

  const peakRam = ramSamples.length ? Math.max(...ramSamples.map((s) => s.peakUsedGb)).toFixed(2) : "n/a";
  const avgRam  = ramSamples.length
    ? (ramSamples.reduce((a, b) => a + b.avgUsedGb, 0) / ramSamples.length).toFixed(2)
    : "n/a";

  const maxPressure = pressureSamples.length ? Math.max(...pressureSamples.map((s) => s.peakPressure)).toFixed(2) : "n/a";
  const avgPressure  = pressureSamples.length
    ? (pressureSamples.reduce((a, b) => a + b.pressureAvg, 0) / pressureSamples.length).toFixed(2)
    : "n/a";  

  const peakSwap = swapSamples.length ? Math.max(...swapSamples.map((s) => s.maxSwap)).toFixed(2) : "n/a";
  const avgSwap  = swapSamples.length
    ? (swapSamples.reduce((a, b) => a + b.maxSwap + b.startingSwap, 0) / (2 * swapSamples.length)).toFixed(2)
    : "n/a";  

  const totalTokens = stats.filter((s) => s.completionTokens).reduce((a, s) => a + s.completionTokens, 0);
  const totalInputToks = stats.filter((s) => s.promptTokens).reduce((a, s) => a + s.promptTokens, 0);
  const totalInputChars = stats.filter((s) => s.inputChars).reduce((a, s) => a + s.inputChars, 0);
  const contextLen = modelInfo?.loaded_context_length ? `${(modelInfo.loaded_context_length / 1000).toFixed(0)}k` : "unknown";
  const quant      = modelInfo?.quantization ?? "unknown";

  console.log(`
─────────────────────────────────────────────────────
Model:           ${model.id}
Context:         ${contextLen}   Quant: ${quant}
─────────────────────────────────────────────────────
Sessions:        ${stats.filter((s) => !s.skipped && !s.error).length} processed  │  ${stats.filter((s) => s.skipped).length} skipped  │  ${stats.filter((s) => s.error).length} errors
Tokens:          ${totalInputToks} total input tokens  (total input chars: ${totalInputChars}, overall chars/tok: ${(totalInputChars/totalInputToks).toFixed(2)})  |  ${totalTokens} total output tokens
Runtime:         total ${totalRuntime.toFixed(2)}s  |  prefill ${totalPrefillTime.toFixed(2)}s  |  gen ${totalGenTime.toFixed(2)}s
   ---
Output tok/s:    avg ${avgTps}  │  peak ${peakTps}  │  min ${minTps}
Prefill tok/s:   avg ${avgPrefill}  |  peak ${peakPrefill}  |  min ${minPrefill}
   ---
RAM (sys):       peak ${peakRam} GB  │  avg ${avgRam} GB
Swap (sys):      peak ${peakSwap} GB  |  avg ${avgSwap} GB
Memory Pressure: peak ${maxPressure}%  |  avg ${avgPressure}%
─────────────────────────────────────────────────────`);
}

// ─── MAIN ────────────────────────────────────────────────────────
async function main() {
  if (DRY_RUN) console.log("🔍 DRY RUN — no uploads or state changes\n");
  if (NO_UPLOAD) console.log("📋 NO-UPLOAD — summaries only, mem0 write skipped\n");

  if (!CONFIG.mem0.apiKey) {
    console.error("MEM0_API_KEY not set");
    process.exit(1);
  }

  const perfStore = loadPerfStore();

  // Auto-register any model in the perf store that isn't in MODELS yet.
  // MODELS entries take precedence (provider overrides etc.); this just fills gaps.
  for (const id of Object.keys(perfStore)) {
    if (!MODELS.find((m) => m.id === id)) {
      //are we just pushing new models to... a runtime variable?
      MODELS.push({ id, provider: "lmstudio" });
    }
  }

  const model     = await selectModel();
  const state     = loadState(model.id);
  const log       = openRunLog(model);

  let modelInfo = null;
  if (model.provider === "lmstudio") {
    modelInfo = await getModelInfo(model.id);
    if (modelInfo) {
      console.log(`Model info: loaded context=${modelInfo.loaded_context_length} quant=${modelInfo.quantization} state=${modelInfo.state}`);
      if (modelInfo.state !== "loaded") {
        console.error(`✗ Model "${model.id}" is not loaded in LM Studio. Load it manually and retry.`);
        process.exit(1);
      }
    } else {
      console.warn(`⚠ Could not fetch model info from LM Studio v0 API — proceeding anyway`);
    }
  }
  //
  console.log(`
  
      ─────────────────────────────────────────────────────────────────────────────
                 |       ${model.id}           |
      ─────────────────────────────────────────────────────────────────────────────

  `);

  // Sample idle GPU RAM after model confirmed loaded, before any inference.
  const idleGb = model.provider === "lmstudio" ? gpuAllocGb() : null;
  if (idleGb != null) console.log(`\n  Idle GPU RAM: ${idleGb} GB`);
  const idleSwap = model.provider === "lmstudio" ? swapUsedGb() : null;
  if (idleSwap != null) console.log(`  Idle Swap RAM: ${idleSwap} GB`);
  const idleMemPressure = model.provider === "lmstudio" ? memPressureLevel() : null;
  if (idleMemPressure != null) console.log(`  Idle Memory Pressure: ${idleMemPressure}%\n`);


  // Context ceiling: use LM Studio's reported loaded_context_length (chars = tokens * 3.5).
  // todo: we will calculate kvcache memory pressure vs context length and restrict max tokens via a regression curve
  // Previously the perfstore was used to look up past fetch failed errors to the api call, but we
  // discovered that it was failing due to timeout, not out of memory issues. thus, i extended the 
  // timeout period and we shouldn't use past errors to restrict token length.
  // That said, too many tokens on a model with a context limit set above 64k tkns,
  // can still cause a fail, but that fail will be either the model spontaneously crashing
  // and lmstudio recording it as unloaded (doesn't distinguish between why it unloaded)
  // or via a kernel panic system crash in which case nothing is recorded as the script crashes too.
  // maybe we could set some kind of state where if the script doesn't update it to reflect success, we assume it failed? deadmanswitch style? probably not relevant

  const CONTEXT_CAP = 64_000 * 3.5; // ~64k tokens
  const effectiveMaxChars = (() => {
    const fromContext = modelInfo?.loaded_context_length
      ? Math.floor(modelInfo.loaded_context_length * 3.5)
      : CONFIG.maxTranscriptChars;
    return NO_TOKEN_CAP ? fromContext : Math.min(fromContext, CONTEXT_CAP);
  })();
  if (!NO_TOKEN_CAP && CONTEXT_CAP < effectiveMaxChars) console.log(`  Max transcript size restricted to: ${effectiveMaxChars} chars instead of loaded model max transcript`);
  if (NO_TOKEN_CAP) console.log(`  --no-token-cap: script ceiling bypassed, using model context limit (${effectiveMaxChars} chars)`);

  const sessions = findSessions();
  const runStats = [];

  console.log(`  Found ${sessions.length} session(s), model: ${model.id}`);
  console.log(`  infer: ${CONFIG.infer}  │  max transcript: ${effectiveMaxChars} chars\n`);

  for (const session of sessions) {
    const isReprocess = REPROCESS_ID === "all" || (REPROCESS_ID && session.sessionId === REPROCESS_ID);
    const stEntry           = state[session.sessionId];
    const alreadySummarized = loadCachedSummary(session.sessionId, model.id) !== null;
    const alreadyUploaded   = stEntry?.uploaded === true;
    if (!isReprocess) {
      if (REPROCESS_ID && REPROCESS_ID !== "all") {
        // targeting a specific session, skip everything else
        continue;
      }
      if (NO_UPLOAD  && alreadySummarized) {
        console.log(`  ⚠ Skipping past ${session.sessionId} — summary file is cached on disk`);
        log.write({ sessionId: session.sessionId, skipped: true, reason: "already_summarized", ts: new Date().toISOString() });
        continue;
      }
      if (!NO_UPLOAD && alreadyUploaded)   {
        console.log(`  ⚠ Skipping past ${session.sessionId} — summary is cached and uploaded to mem0`);
        log.write({ sessionId: session.sessionId, skipped: true, reason: "already_uploaded", ts: new Date().toISOString() });
        continue;
      }
    }

    const entries    = parseSession(session.filePath);
    const transcript = buildTranscript(entries);
    const lineCount  = transcript.split("\n").length;
    const convEntries = entries.filter(e => e.type === "user" || e.type === "assistant");
    const startedAt  = convEntries[0]?.timestamp ?? null;
    const endedAt    = convEntries[convEntries.length - 1]?.timestamp ?? null;

    if (transcript.length > effectiveMaxChars) {
      console.log(`  ⚠ Skipping ${session.sessionId} (${transcript.length} chars, exceeds context limit — use --no-token-cap to override)`);
      runStats.push({ sessionId: session.sessionId, skipped: true, reason: "context_overflow", chars: transcript.length });
      log.write({ sessionId: session.sessionId, skipped: true, reason: "context_overflow", chars: transcript.length, ts: new Date().toISOString() });
      continue;
    }

    let finalTranscript = transcript;
    if (transcript.length > effectiveMaxChars) {
      console.warn(`  ⚠ Running ${transcript.length} char session on model with ${modelInfo.loaded_context_length} max token length, above the recommended ${effectiveMaxChars} maximum chars`);
    }

    if (finalTranscript.length < 500) {
      console.log(`  ⚠ Skipping ${session.sessionId} (${finalTranscript.length} chars — too short to summarize)`);
      runStats.push({ sessionId: session.sessionId, skipped: true, reason: "too_short", chars: finalTranscript.length });
      log.write({ sessionId: session.sessionId, skipped: true, reason: "too_short", chars: finalTranscript.length, ts: new Date().toISOString() });
      continue;
    }

    console.log(`      |------${model.id}------|`);
    console.log(`\n   Session ${runStats.length} of ${sessions.length}`);
    console.log(`\n...\n  💪  Processing ${session.sessionId} (${lineCount} lines, ${finalTranscript.length} chars)…`);
    //the two following lines i moved outside of the try block as they didn't get scoped into the catch. also, sampler didn't have a var/let/etc in front of it - either i missed its declaration somewhere or js said it's totally cool anyway...
    let summary, tps, prefillTps, ttft, genTime, completionTokens, promptTokens, reasoningTokens, peakUsedGb, avgUsedGb, preSessionIdleGb, startingSwap, maxSwap, peakPressure, pressureAvg;
    let sampler = startRamSampler();
    let runtime;
    try {
      //does the ignore cache logic have to be so hard to read?
      const cached = isReprocess ? null : loadCachedSummary(session.sessionId, model.id);
      if (cached) {
        summary = cached;
        tps = null; prefillTps = null; completionTokens = null; peakUsedGb = null; avgUsedGb = null; startingSwap = null; maxSwap = null; peakPressure = null; pressureAvg = null;
        console.log(`  ↩ Using cached summary`);
      } else {
        preSessionIdleGb = model.provider === "lmstudio" ? gpuAllocGb() : null;
        let startTime = performance.now();

        ({ summary, tps, ttft, genTime, completionTokens, promptTokens, reasoningTokens } = await summarizeSession(finalTranscript, model));
        ({ peakUsedGb, avgUsedGb, startingSwap, maxSwap, peakPressure, pressureAvg} = sampler.stop());
        
        runtime = Math.floor(.001 * (performance.now() - startTime));
        if (ttft != null) {
          prefillTps = (promptTokens / ttft).toFixed(2);
          //console.log(`  ⏳  Timer says processing completed in ${runtime} sec.`);
          console.log(`  ⌛️  Total time is ttft (${ttft}s) + genTime (${genTime}s) = ${(ttft + genTime).toFixed(2)}s`);
          if (ttft < genTime) console.log(`  ⚠️   Time to first token or prefill time may be inaccurate if there is a KV cache hit.`); //may need to find a way to track, until then filter data where prefill < gen
        }
        if (completionTokens != null) {
          console.log(`  🎟️   Prompt tokens: ${promptTokens} (${finalTranscript.length}chars). Ratio: ${(finalTranscript.length / promptTokens).toFixed(2)} chars/tok`);
          console.log(`  💎  Output tokens: ${completionTokens} (${reasoningTokens ?? null} reasoning)`);
        }
        if (tps != null) {
          //console.log(`  ⏱️  Based on tps and completion tokens, generation took ${Math.floor(completionTokens / tps)}sec and prefill took ${runtime - Math.floor(completionTokens / tps)} sec.`);
          console.log(`  ⚡️  Output: ${tps.toFixed(1)} tok/s | (${completionTokens} tokens) | input: ${prefillTps} tok/s (${promptTokens} tokens)`);
        }
        if (peakUsedGb != null) console.log(`  🧠  Pre Session RAM ${preSessionIdleGb}GB | RAM peak ${peakUsedGb} GB | avg ${avgUsedGb} GB`);
        if (maxSwap != null) console.log(`  😰  Starting RAM Swap ${startingSwap}GB | Swap peak ${maxSwap} GB`);
        if (peakPressure != null) console.log(`  🥵  Peak memory pressure ${peakPressure}% | Average memory pressure ${pressureAvg}%`);

        console.log(`  📖  summary preview: \n
______________________________________________\n`
          + summary.substring(0, 1000) + `
______________________________________________\n`);
        log.write({ sessionId: session.sessionId, summaryPreview: summary.substring(0, 1000), ts: new Date().toISOString() });

        const summaryTs    = startedAt ? startedAt.slice(0, 16).replace("T", " ") : new Date().toISOString().slice(0, 16).replace("T", " ");
        const summaryTsEnd = endedAt   ? endedAt.slice(0, 16).replace("T", " ")   : null;
        summary = `[${summaryTs}${summaryTsEnd ? ` → ${summaryTsEnd}` : ""}]\n${summary}`;
        saveCachedSummary(session.sessionId, model.id, summary, isReprocess);
        console.log(`  ✓ Summary cached`);
      }

      if (!DRY_RUN) {
        state[session.sessionId] = {
          ...(state[session.sessionId] || {}),
          startedAt,
          endedAt,
          summarizedAt:    new Date().toISOString(),
          summarizedBy:    model.id,
          transcriptLines: lineCount,
          transcriptChars: finalTranscript.length,
          summarized:      true,
          uploaded:        state[session.sessionId]?.uploaded ?? false,
        };
        saveState(state, model.id);
      }

      await uploadToMem0(summary, session.sessionId, session.projectDir, model);

      if (!DRY_RUN && !NO_UPLOAD) {
        state[session.sessionId].uploaded   = true;
        state[session.sessionId].uploadedAt = new Date().toISOString();
        saveState(state, model.id);
      }

      if (!DRY_RUN && peakUsedGb != null) {
        appendPerfEntry(perfStore, model.id, {
          ts:             new Date().toISOString(),
          session:        session.sessionId,
          idleGb,
          preSessionIdleGb: preSessionIdleGb ?? null,
          idleSwap:       idleSwap,
          idleMemPressure: idleMemPressure,
          peakGb:         peakUsedGb,
          avgGb:          avgUsedGb,
          ttft:           ttft,
          genTime:        genTime,
          promptTokens:   promptTokens,
          loadedContextChars:  effectiveMaxChars,
          startingSwap:   startingSwap,
          maxSwap:        maxSwap,
          peakPressure:   peakPressure,
          pressureAvg:    pressureAvg,
          tps:            tps ?? null,
          completionTokens: completionTokens ?? null,
          reasoningTokens: reasoningTokens ?? null,
          transcriptChars: finalTranscript.length,
        });
      }

      const inputChars = finalTranscript.length;
      runStats.push({ sessionId: session.sessionId, ttft, genTime, tps, prefillTps, promptTokens, completionTokens, inputChars, peakUsedGb, avgUsedGb, startingSwap, maxSwap, peakPressure, pressureAvg });
      log.write({ sessionId: session.sessionId, model: model.id, ttft, genTime, tps, prefillTps, promptTokens, completionTokens, peakUsedGb, avgUsedGb, startingSwap, maxSwap, peakPressure, pressureAvg, ts: new Date().toISOString() });

      console.log(`  ✓ ${DRY_RUN ? "Dry-run complete" : NO_UPLOAD ? "Summarized (no upload)" : "Uploaded"}: ${session.sessionId}`);
    } catch (err) {
      console.error(`  ✗ Failed: ${session.sessionId} — ${err.message}`);
      runStats.push({ sessionId: session.sessionId, error: err.message });
      log.write({ sessionId: session.sessionId, model: model.id, error: err.message, ts: new Date().toISOString() });
      if (!DRY_RUN && model.provider === "lmstudio") {
        const partial = sampler ? sampler.stop() : { peakUsedGb: null, avgUsedGb: null };
        console.log(`  🧠 Pre Session RAM ${preSessionIdleGb}GB | RAM peak ${partial.peakUsedGb} GB | avg ${partial.avgUsedGb} GB`);
        //make sure this matches successful session runs in content
        appendPerfEntry(perfStore, model.id, {
          ts:              new Date().toISOString(),
          idleGb,
          preSessionIdleGb: preSessionIdleGb ?? null,
          peakGb:          partial.peakUsedGb,
          avgGb:           partial.avgUsedGb,
          tps:             null,
          runtime:         runtime,
          loadedContextChars:   effectiveMaxChars,
          completionTokens: null,
          transcriptChars: finalTranscript.length,
          failed:          true,
          failReason:      err.message,
        });
      }
    }
  }

  log.close();
  printSummary(model, modelInfo, runStats);
  console.log(`Log: ${log.path}\n`);
}

main().then(() => process.exit(0));
