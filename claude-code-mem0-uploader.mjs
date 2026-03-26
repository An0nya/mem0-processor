import fs from "fs";
import path from "path";
import os from "os";
import Anthropic from "@anthropic-ai/sdk";

// ─── CONFIG ──────────────────────────────────────────────────────
const CONFIG = {
    /*summarizer: {
      provider: "lmstudio",
      model: "google/gemma-3-4b",
      endpoint: "http://localhost:1234/v1",
    },*/
    /*summarizer: {
      provider: "lmstudio",
      model: "liquid/lfm2.5-1.2b",
      endpoint: "http://localhost:1234/v1",
    },*/
    /*summarizer: {
      provider: "lmstudio",
      model: "microsoft/phi-4-mini-reasoning",
      endpoint: "http://localhost:1234/v1",
    },*/
    /*summarizer: {
      provider: "lmstudio",
      model: "google/gemma-3-12b",
      endpoint: "http://localhost:1234/v1",
    },*/
    summarizer: {
      provider: "lmstudio",
      model: "qwen/qwen3-4b-thinking-2507",
      endpoint: "http://localhost:1234/v1",
    },
    /*summarizer: {
      provider: "lmstudio",
      model: "qwen/qwen3.5-9b",
      endpoint: "http://localhost:1234/v1",
    },*/
    /*summarizer: {
      provider: "anthropic",
      model: "claude-haiku-4-5-20251001",
      endpoint: null,
    },*/

  mem0: {
    apiKey: process.env.MEM0_API_KEY,
    agentId: "claude-code-sessions",
  },
  minMessages: 20,
  toolResultMaxChars: 1000,
  transcriptMaxChars: 150000,
};

const PROJECTS_DIR = path.join(os.homedir(), ".claude", "projects");
const STATE_FILE = path.join(os.homedir(), ".claude", "mem0_upload_state.json");
const SUMMARIES_DIR = path.join(os.homedir(), ".claude", "mem0_summaries");

const DRY_RUN = process.argv.includes("--dry-run");

// Derive a safe user_id slug from model name: "google/gemma-3-12b" → "anya-google-gemma-3-12b"
function modelToUserId(model) {
  const slug = model.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return `anya-${slug}`;
}

// Composite state key: sessionId::modelId
function stateKey(sessionId, model) {
  return `${sessionId}::${model}`;
}

// ─── STATE TRACKING ──────────────────────────────────────────────
function loadState() {
  if (!fs.existsSync(STATE_FILE)) return {};
  return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ─── SUMMARY CACHE ───────────────────────────────────────────────
function summaryPath(sessionId, model) {
  fs.mkdirSync(SUMMARIES_DIR, { recursive: true });
  const slug = model.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return path.join(SUMMARIES_DIR, `${sessionId}--${slug}.txt`);
}

function loadCachedSummary(sessionId, model) {
  const p = summaryPath(sessionId, model);
  if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
  return null;
}

function saveCachedSummary(sessionId, model, summary) {
  fs.writeFileSync(summaryPath(sessionId, model), summary);
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
      sessions.push({
        sessionId,
        projectDir,
        filePath: path.join(projectPath, file),
      });
    }
  }
  return sessions;
}

// ─── JSONL PARSING ───────────────────────────────────────────────
function parseSession(filePath) {
  const raw = fs.readFileSync(filePath, "utf8");
  return raw
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      try { return JSON.parse(line); }
      catch { return null; }
    })
    .filter(Boolean);
}

// ─── CONTENT EXTRACTION ─────────────────────────────────────────
function extractContentBlocks(entry) {
  if (entry.message?.content) {
    const model = entry.message?.model || null;
    return { blocks: entry.message.content, entryType: entry.type, model };
  }
  if (entry.data?.message?.message?.content) {
    const model = entry.data.message.message.model || "unknown";
    return { blocks: entry.data.message.message.content, entryType: entry.data.message.type, model };
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
        const speaker = entryType === "user" ? "USER" : "ASSISTANT";
        lines.push(`[${speaker}${agentTag}] ${block.text}`);

      } else if (block.type === "tool_use") {
        const inputPreview = JSON.stringify(block.input).slice(0, 300);
        lines.push(`[TOOL_CALL${agentTag}] ${block.name}(${inputPreview})`);

      } else if (block.type === "tool_result") {
        const raw = typeof block.content === "string"
          ? block.content
          : JSON.stringify(block.content);

        if (raw.includes("<persisted-output>")) {
          const sizeMatch = raw.match(/Output too large \([\d.]+KB\)/);
          lines.push(`[TOOL_RESULT${agentTag}] ${sizeMatch?.[0] || "Large output"} — persisted to disk`);
        } else {
          const tag = block.is_error ? "TOOL_ERROR" : "TOOL_RESULT";
          lines.push(`[${tag}${agentTag}] ${raw.slice(0, cap)}`);
        }
      }
    }
  }

  const transcript = lines.join("\n");

  if (transcript.length > CONFIG.transcriptMaxChars) {
    console.warn(`  ⚠ Transcript truncated from ${transcript.length} to ${CONFIG.transcriptMaxChars} chars`);
    return transcript.slice(0, CONFIG.transcriptMaxChars) + "\n[TRUNCATED]";
  }

  return transcript;
}

// ─── SUMMARIZATION ───────────────────────────────────────────────
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

const anthropic = CONFIG.summarizer.provider === "anthropic" ? new Anthropic() : null;

async function summarizeSession(transcript) {
  if (CONFIG.summarizer.provider === "anthropic") {
    const response = await anthropic.messages.create({
      model: CONFIG.summarizer.model,
      max_tokens: 2048,
      system: SUMMARIZATION_PROMPT,
      messages: [{ role: "user", content: transcript }],
    });
    return response.content[0].text;
  }

  if (CONFIG.summarizer.provider === "lmstudio") {
    const response = await fetch(`${CONFIG.summarizer.endpoint}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: CONFIG.summarizer.model,
        messages: [
          { role: "system", content: SUMMARIZATION_PROMPT },
          { role: "user", content: transcript },
        ],
        max_tokens: 2048,
      }),
    });
    const data = await response.json();
    let content = data.choices[0].message.content;
    content = content.replace(/<think>[\s\S]*?<\/think>/i, "").trim();
    return content;
  }

  throw new Error(`Unknown provider: ${CONFIG.summarizer.provider}`);
}

// ─── MEM0 UPLOAD ─────────────────────────────────────────────────
async function uploadToMem0(summary, sessionId) {
  const userId = modelToUserId(CONFIG.summarizer.model);

  if (DRY_RUN) {
    console.log(`  [DRY-RUN] Would upload to mem0:`);
    console.log(`    user_id: ${userId}`);
    console.log(`    run_id:  ${sessionId}`);
    console.log(`    summary: ${summary.slice(0, 200)}...`);
    return;
  }

  const response = await fetch("https://api.mem0.ai/v1/memories/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Token ${CONFIG.mem0.apiKey}`,
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: summary }],
      agent_id: CONFIG.mem0.agentId,
      user_id: userId,
      run_id: sessionId,
      infer: true,
      metadata: {
        summarizedBy: CONFIG.summarizer.model,
        provider: CONFIG.summarizer.provider,
      },
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`mem0 ${response.status}: ${body.slice(0, 200)}`);
  }

  return response.json();
}

// ─── MAIN ────────────────────────────────────────────────────────
async function main() {
  if (DRY_RUN) console.log("🔍 DRY RUN — no uploads or state changes will occur\n");

  const state = loadState();
  const sessions = findSessions();
  let processed = 0;
  const model = CONFIG.summarizer.model;

  console.log(`Found ${sessions.length} session(s), model: ${model}`);

  for (const session of sessions) {
    const key = stateKey(session.sessionId, model);
    if (state[key]) continue;

    const entries = parseSession(session.filePath);
    const transcript = buildTranscript(entries);
    const lineCount = transcript.split("\n").length;

    if (lineCount < CONFIG.minMessages) {
      console.log(`Skipping ${session.sessionId} (${lineCount} lines, below threshold)`);
      continue;
    }

    console.log(`Processing ${session.sessionId} (${lineCount} lines, ${transcript.length} chars)...`);

    try {
      // Use cached summary if available, otherwise summarize and cache
      let summary = loadCachedSummary(session.sessionId, model);
      if (summary) {
        console.log(`  ↩ Using cached summary`);
      } else {
        summary = await summarizeSession(transcript);
        saveCachedSummary(session.sessionId, model, summary);
        console.log(`  ✓ Summary cached`);
      }

      await uploadToMem0(summary, session.sessionId);

      if (!DRY_RUN) {
        state[key] = {
          processedAt: new Date().toISOString(),
          summarizedBy: model,
          userId: modelToUserId(model),
          transcriptLines: lineCount,
          transcriptChars: transcript.length,
        };
        saveState(state);
      }

      processed++;
      console.log(`  ✓ ${DRY_RUN ? "Dry-run complete" : "Uploaded"}: ${session.sessionId}`);
    } catch (err) {
      console.error(`  ✗ Failed: ${session.sessionId} — ${err.message}`);
    }
  }

  console.log(`\nDone. ${DRY_RUN ? "Dry-run" : "Processed"} ${processed} session(s).`);
}

main();
