// claude-code-mem0-uploader-v5.mjs
//
// Summarizes Claude Code session logs via a local or cloud LLM,
// then uploads to Mem0 under a flat user_id namespace.
//
// KEY DESIGN DECISIONS:
//   - All memories go to user_id="anya-sessions" with NO run_id or agent_id.
//   - infer=true (default): Mem0 decomposes summaries into atomic facts.
//     Set INFER=false env var to store summaries as single blobs instead.
//   - POST /v1/memories/ is the correct add endpoint.
//   - Per-model state files prevent race conditions when running two models
//     in parallel. State file is auto-named by model slug.
//   - LM Studio v0 API used at startup to get max_context_length per model.
//     JIT loading is assumed ON — all downloaded models are considered usable.
//   - tps pulled from LM Studio response stats object (more accurate than
//     wall-clock calculation).
//   - RAM sampled via os.freemem() during summarization (peak + avg).
//   - Runs are logged to ~/.claude/mem0_logs/ as JSONL for later analysis.

import fs from "fs";
import path from "path";
import os from "os";
import Anthropic from "@anthropic-ai/sdk";

// ─── MODEL REGISTRY ──────────────────────────────────────────────
// All non-junk models worth benchmarking. Select with --model <partial-id>.
// First entry is the default if --model not specified.
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
  { id: "claude-haiku-4-5-20251001",                       provider: "anthropic" },
];

// ─── CONFIG ──────────────────────────────────────────────────────
const LMSTUDIO_ENDPOINT = "http://localhost:1234";

const CONFIG = {
  mem0: {
    apiKey: process.env.MEM0_API_KEY,
    userId: "anya-sessions",
  },
  infer: process.env.INFER !== "false",
  minMessages: 20,
  toolResultMaxChars: 1000,
  // Sessions with transcripts above this char count are skipped by default.
  // Override with --force-truncate to truncate-and-process instead.
  maxTranscriptChars: 180000,
};

const PROJECTS_DIR  = path.join(os.homedir(), ".claude", "projects");
const SUMMARIES_DIR = path.join(os.homedir(), ".claude", "mem0_summaries");
const LOGS_DIR      = path.join(os.homedir(), ".claude", "mem0_logs");

const DRY_RUN       = process.argv.includes("--dry-run");
const FORCE_TRUNCATE = process.argv.includes("--force-truncate");

// ─── MODEL SELECTION ─────────────────────────────────────────────
function selectModel() {
  const flag = process.argv.indexOf("--model");
  if (flag !== -1 && process.argv[flag + 1]) {
    const query = process.argv[flag + 1].toLowerCase();
    const match = MODELS.find((m) => m.id.toLowerCase().includes(query));
    if (!match) {
      console.error(`No model matching "${query}" in registry. Available:\n${MODELS.map((m) => `  ${m.id}`).join("\n")}`);
      process.exit(1);
    }
    return match;
  }
  return MODELS[0];
}

// ─── STATE TRACKING ──────────────────────────────────────────────
// Per-model state files prevent race conditions when running two models
// concurrently in separate terminals.
function stateFilePath(modelId) {
  const slug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return path.join(os.homedir(), ".claude", `mem0_upload_state--${slug}.json`);
}

function loadState(modelId) {
  const p = stateFilePath(modelId);
  if (!fs.existsSync(p)) return {};
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function saveState(state, modelId) {
  fs.writeFileSync(stateFilePath(modelId), JSON.stringify(state, null, 2));
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

function saveCachedSummary(sessionId, modelId, summary) {
  fs.writeFileSync(summaryPath(sessionId, modelId), summary);
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

async function listLoadedModels() {
  try {
    const res = await fetch(`${LMSTUDIO_ENDPOINT}/api/v0/models?state=loaded`);
    if (!res.ok) return [];
    const data = await res.json();
    return (data.data || []).map((m) => m.id);
  } catch {
    return [];
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
      const sessionId = path.basename(file, ".jsonl");
      sessions.push({ sessionId, projectDir, filePath: path.join(projectPath, file) });
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
function startRamSampler(intervalMs = 500) {
  const samples = [];
  const interval = setInterval(() => samples.push(os.freemem()), intervalMs);
  return {
    stop() {
      clearInterval(interval);
      if (samples.length === 0) return { peakUsedGb: null, avgUsedGb: null };
      const totalMem = os.totalmem();
      const usedSamples = samples.map((free) => totalMem - free);
      const peak = Math.max(...usedSamples);
      const avg = usedSamples.reduce((a, b) => a + b, 0) / usedSamples.length;
      return {
        peakUsedGb: +(peak / 1e9).toFixed(2),
        avgUsedGb:  +(avg  / 1e9).toFixed(2),
      };
    },
  };
}

// ─── SUMMARIZATION PROMPT ────────────────────────────────────────
const SUMMARIZATION_PROMPT = `
You are summarizing a Claude Code session log for long-term memory storage.

CRITICAL REQUIREMENTS:
1. Decrypt ALL acronyms and jargon on first use (e.g. "MCP (Model Context Protocol)")
2. Explicitly attribute every insight, decision, and action:
   - [USER] = the user proposed, diagnosed, caught, or independently understood this
   - [CLAUDE] = Claude produced this and the user has NOT confirmed understanding
   - [USER-APPROVED] = Claude proposed, user approved, but depth of understanding is uncertain
3. Flag cases where Claude was confidently wrong and whether the user caught it
4. Low-signal user approvals ("okay", "sounds good", "sure") should be tagged [USER-APPROVED], not [USER]
5. Note competence signals per topic — not just "we did X" but "user independently identified Y"
6. Sub-agent calls (marked with "sub-agent: model-name") are delegated research — attribute to Claude, not the user

OUTPUT FORMAT:
- Session topic summary (1-2 sentences)
- Key decisions and who drove them (attributed)
- Technical concepts covered and user's apparent comprehension level
- Tool usage patterns (errors, retries, unnecessary calls)
- Mistakes made (by either party) and whether they were caught
- Open threads / unfinished work
`.trim();

// ─── SUMMARIZATION ───────────────────────────────────────────────
const anthropic = new Anthropic();

async function summarizeSession(transcript, model) {
  if (model.provider === "anthropic") {
    const response = await anthropic.messages.create({
      model: model.id,
      max_tokens: 2048,
      system: SUMMARIZATION_PROMPT,
      messages: [{ role: "user", content: transcript }],
    });
    // Anthropic SDK doesn't give tps; return null for those fields
    return { summary: response.content[0].text, tps: null, completionTokens: response.usage.output_tokens };
  }

  if (model.provider === "lmstudio") {
    const response = await fetch(`${LMSTUDIO_ENDPOINT}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.id,
        messages: [
          { role: "system", content: SUMMARIZATION_PROMPT },
          { role: "user",   content: transcript },
        ],
        max_tokens: 2048,
      }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`LM Studio ${response.status}: ${body.slice(0, 300)}`);
    }

    const data = await response.json();
    // LM Studio v0 returns stats.tokens_per_second on the response object
    const tps = data.stats?.tokens_per_second ?? null;
    const completionTokens = data.usage?.completion_tokens ?? null;
    let summary = data.choices[0].message.content;
    summary = summary.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
    return { summary, tps, completionTokens };
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
function printSummary(model, modelInfo, stats) {
  const tpsSamples = stats.filter((s) => s.tps != null).map((s) => s.tps);
  const ramSamples = stats.filter((s) => s.peakUsedGb != null);

  const avgTps  = tpsSamples.length ? (tpsSamples.reduce((a, b) => a + b, 0) / tpsSamples.length).toFixed(1) : "n/a";
  const peakTps = tpsSamples.length ? Math.max(...tpsSamples).toFixed(1) : "n/a";
  const minTps  = tpsSamples.length ? Math.min(...tpsSamples).toFixed(1) : "n/a";

  const peakRam = ramSamples.length ? Math.max(...ramSamples.map((s) => s.peakUsedGb)).toFixed(2) : "n/a";
  const avgRam  = ramSamples.length
    ? (ramSamples.reduce((a, b) => a + b.avgUsedGb, 0) / ramSamples.length).toFixed(2)
    : "n/a";

  const totalTokens = stats.filter((s) => s.completionTokens).reduce((a, s) => a + s.completionTokens, 0);

  const contextLen = modelInfo?.max_context_length ? `${(modelInfo.max_context_length / 1000).toFixed(0)}k` : "unknown";
  const quant      = modelInfo?.quantization ?? "unknown";

  console.log(`
─────────────────────────────────────────────────────
Model:      ${model.id}
Context:    ${contextLen}   Quant: ${quant}
─────────────────────────────────────────────────────
Sessions:   ${stats.filter((s) => !s.skipped && !s.error).length} processed  │  ${stats.filter((s) => s.skipped).length} skipped  │  ${stats.filter((s) => s.error).length} errors
Tokens:     ${totalTokens} total output tokens
tok/s:      avg ${avgTps}  │  peak ${peakTps}  │  min ${minTps}
RAM (sys):  peak ${peakRam} GB  │  avg ${avgRam} GB
─────────────────────────────────────────────────────`);
}

// ─── MAIN ────────────────────────────────────────────────────────
async function main() {
  if (DRY_RUN) console.log("🔍 DRY RUN — no uploads or state changes\n");

  if (!CONFIG.mem0.apiKey) {
    console.error("MEM0_API_KEY not set");
    process.exit(1);
  }

  const model = selectModel();
  const state = loadState(model.id);
  const log   = openRunLog(model);

  // Fetch model info from LM Studio v0 API (best-effort)
  let modelInfo = null;
  if (model.provider === "lmstudio") {
    modelInfo = await getModelInfo(model.id);
    if (modelInfo) {
      console.log(`Model info: context=${modelInfo.max_context_length} quant=${modelInfo.quantization} state=${modelInfo.state}`);
      if (modelInfo.state !== "loaded") {
        console.error(`✗ Model "${model.id}" is not loaded in LM Studio. Load it manually and retry.`);
        process.exit(1);
      }
    } else {
      console.warn(`⚠ Could not fetch model info from LM Studio v0 API — proceeding anyway`);
    }
  }

  const effectiveMaxChars = modelInfo?.max_context_length
    ? Math.min(CONFIG.maxTranscriptChars, Math.floor(modelInfo.max_context_length * 3.5)) // rough chars-per-token
    : CONFIG.maxTranscriptChars;

  const sessions = findSessions();
  const runStats = [];

  console.log(`Found ${sessions.length} session(s), model: ${model.id}`);
  console.log(`infer: ${CONFIG.infer}  │  max transcript: ${effectiveMaxChars} chars\n`);

  for (const session of sessions) {
    if (state[session.sessionId]) continue;

    const entries    = parseSession(session.filePath);
    const transcript = buildTranscript(entries);
    const lineCount  = transcript.split("\n").length;

    if (lineCount < CONFIG.minMessages) {
      console.log(`Skipping ${session.sessionId} (${lineCount} lines, below threshold)`);
      runStats.push({ sessionId: session.sessionId, skipped: true, reason: "below_threshold" });
      log.write({ sessionId: session.sessionId, skipped: true, reason: "below_threshold", ts: new Date().toISOString() });
      continue;
    }

    if (transcript.length > effectiveMaxChars && !FORCE_TRUNCATE) {
      console.log(`⚠ Skipping ${session.sessionId} (${transcript.length} chars, exceeds context limit — use --force-truncate to override)`);
      runStats.push({ sessionId: session.sessionId, skipped: true, reason: "context_overflow", chars: transcript.length });
      log.write({ sessionId: session.sessionId, skipped: true, reason: "context_overflow", chars: transcript.length, ts: new Date().toISOString() });
      continue;
    }

    let finalTranscript = transcript;
    if (transcript.length > effectiveMaxChars) {
      console.warn(`  ⚠ Truncating ${transcript.length} → ${effectiveMaxChars} chars`);
      finalTranscript = transcript.slice(0, effectiveMaxChars) + "\n[TRUNCATED]";
    }

    console.log(`Processing ${session.sessionId} (${lineCount} lines, ${finalTranscript.length} chars)…`);

    try {
      let summary, tps, completionTokens, peakUsedGb, avgUsedGb;

      const cached = loadCachedSummary(session.sessionId, model.id);
      if (cached) {
        summary = cached;
        tps = null; completionTokens = null; peakUsedGb = null; avgUsedGb = null;
        console.log(`  ↩ Using cached summary`);
      } else {
        const sampler = startRamSampler();
        ({ summary, tps, completionTokens } = await summarizeSession(finalTranscript, model));
        ({ peakUsedGb, avgUsedGb } = sampler.stop());

        if (tps != null) console.log(`  ⚡ ${tps.toFixed(1)} tok/s (${completionTokens} tokens)`);
        if (peakUsedGb != null) console.log(`  🧠 RAM peak ${peakUsedGb} GB  avg ${avgUsedGb} GB`);

        saveCachedSummary(session.sessionId, model.id, summary);
        console.log(`  ✓ Summary cached`);
      }

      await uploadToMem0(summary, session.sessionId, session.projectDir, model);

      if (!DRY_RUN) {
        state[session.sessionId] = {
          processedAt:     new Date().toISOString(),
          summarizedBy:    model.id,
          transcriptLines: lineCount,
          transcriptChars: finalTranscript.length,
        };
        saveState(state, model.id);
      }

      runStats.push({ sessionId: session.sessionId, tps, completionTokens, peakUsedGb, avgUsedGb });
      log.write({ sessionId: session.sessionId, model: model.id, tps, completionTokens, peakUsedGb, avgUsedGb, ts: new Date().toISOString() });

      console.log(`  ✓ ${DRY_RUN ? "Dry-run complete" : "Uploaded"}: ${session.sessionId}`);
    } catch (err) {
      console.error(`  ✗ Failed: ${session.sessionId} — ${err.message}`);
      runStats.push({ sessionId: session.sessionId, error: err.message });
      log.write({ sessionId: session.sessionId, model: model.id, error: err.message, ts: new Date().toISOString() });
    }
  }

  log.close();
  printSummary(model, modelInfo, runStats);
  console.log(`Log: ${log.path}\n`);
}

main();
