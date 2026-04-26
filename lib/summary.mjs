import fs from "fs";
import path from "path";
import { SUMMARIES_DIR, ARCHIVE_DIR, LOGS_DIR, LLAMA_RESPONSES_DIR } from "./paths.mjs";
import { LLAMA_PORT, resolveLaunch } from "./registry.mjs";

// ─── SUMMARY CACHE ───────────────────────────────────────────────

/**
 * Returns the filesystem path for a cached summary file.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @param {string} modelId
 * @returns {string}
 */
export function summaryPath(sessionId, sessionSlug, modelId) {
  fs.mkdirSync(SUMMARIES_DIR, { recursive: true });
  const modelSlug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  const prefix = sessionSlug ? `${sessionSlug}--${sessionId.slice(0, 8)}` : sessionId;
  return path.join(SUMMARIES_DIR, `${prefix}--${modelSlug}.txt`);
}

/**
 * Strips YAML frontmatter from the top of a string.
 * @param {string} raw
 * @returns {string}
 */
export function stripFrontmatter(raw) {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end === -1) return raw;
  return raw.slice(end + 5);
}

/**
 * Loads a cached summary (without frontmatter), or null if not found.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @param {string} modelId
 * @returns {string|null}
 */
export function loadCachedSummary(sessionId, sessionSlug, modelId) {
  const p = summaryPath(sessionId, sessionSlug, modelId);
  if (fs.existsSync(p)) return stripFrontmatter(fs.readFileSync(p, "utf8"));
  return null;
}

/**
 * Builds a YAML frontmatter block from a metadata object.
 * @param {object|null} meta
 * @returns {string}
 */
export function buildFrontmatter(meta) {
  if (!meta || Object.keys(meta).length === 0) return "";
  const lines = ["---"];
  for (const [k, v] of Object.entries(meta)) {
    if (v === undefined) continue;
    const val = v === null ? "null" : typeof v === "string" ? JSON.stringify(v) : String(v);
    lines.push(`${k}: ${val}`);
  }
  lines.push("---", "");
  return lines.join("\n");
}

/**
 * Writes a summary to cache. Optionally archives the previous version first.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @param {string} modelId
 * @param {string} summary
 * @param {boolean} [archive=false]
 * @param {object|null} [meta=null]
 */
export function saveCachedSummary(sessionId, sessionSlug, modelId, summary, archive = false, meta = null) {
  const p = summaryPath(sessionId, sessionSlug, modelId);
  if (archive && fs.existsSync(p)) {
    const modelSlug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
    const archiveDir = path.join(ARCHIVE_DIR, modelSlug);
    fs.mkdirSync(archiveDir, { recursive: true });
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const prefix = sessionSlug ? `${sessionSlug}--${sessionId.slice(0, 8)}` : sessionId;
    fs.renameSync(p, path.join(archiveDir, `${prefix}--${ts}.txt`));
  }
  fs.writeFileSync(p, buildFrontmatter(meta) + summary);
}

// ─── SUMMARIZATION ───────────────────────────────────────────────

export const SUMMARIZATION_PROMPT = `
Audit the interactions in this Claude Code session. \nWrite a standalone analysis of meta issues from a process-level standpoint\n\"Standalone\" means readable cold with no transcript access.\nThis analysis helps the user learn where they trusted Claude too much,\nwhere Claude acted faster than it should have, miscommunication, and where context or time was wasted. \nCatching code bugs is secondary to surfacing these trust-calibration and efficiency signals.\n## Goal\nWhat the user was actually trying to accomplish. Infer the real\nobjective from full context, not the requests at face value.\n1–3 sentences.\n## What Happened & Why\nNarrative, not a log. What drove each major turn? What assumptions\nwere active? Where did plans change, and why? Do not enumerate tool\ncalls unless they indicate friction.\nIf the session wandered, re-did work, or pivoted mid-task, say so plainly.\n## Competence & Clarifications\nTwo things, distinctly:\n- What the user independently knew, discovered, or identified. \n  Explain how you reached this conclusion.\n- What the user asked Claude to explain or justify. Clarifying\n  questions (\"wtf is that syntax,\" \"is that timezone-safe\") are\n  competence signals about how the user is thinking — not mistakes —\n  even when Claude's answer is correct and no change results. \n  Explain if this helped resolve an issue or misunderstanding and how\nNote gaps: places the user deferred without understanding.\n## Mistakes & Overreach\nLabel each item as ERROR, MISCOMMUNICATION, or OVERREACH and explain your reasoning\n- ERROR: something wrong was produced. Record who made it, if and how\n  it was caught, whether any process (test, validation, obvious\n  failure) would have caught it, and whether it was only caught\n  by luck because someone happened to look. For every ERROR, explicitly\n  state the catch mechanism — what process, test, or observation\n  surfaced it. If the answer is \"the user happened to re-read their\n  own notes\" or \"the user noticed unexpected behavior,\" say that\n  plainly. Do not soften this to \"resolved quickly\" or \"minor friction.\"\n- MISCOMMUNICATION: indicate who (user or Claude) misunderstood\n  an intention, command, question, or affirmation, and how this \n  miscommunication affected the outcome.\n- OVERREACH: Claude took an action without pausing when it should\n  have asked — running tools, editing files, picking an approach —\n  even if the result was fine. Also include cases where Claude\n  answered from assumption rather than reading available context.\n## Friction Points\nRejected edits, interruptions, re-reads. For each, say which bucket:\ngenuine catch, user confusion or caution, or Claude moving too fast.\nThese are primary signals — do not omit them even if they resolved\ncleanly. Explain the significance or consequence of these friction points.\n## Waste & Efficiency\nWhere context, tokens, or time got burned unnecessarily. Examples:\nClaude reading files it didn't need, running bash before asking\nwhere a file lived, re-doing work because it skipped reading an\nexisting file, pulling large tool output that didn't inform the\nnext step. Brief — one paragraph or a short list.\n## Decisions (attributed)\n[USER]              independently proposed or diagnosed\n[USER-APPROVED]     user said okay/sure without engaging. This means\n                    the user accepted without evaluating the decision.\n                    If the user asked a question first and then accepted\n                    the answer, that is [USER-CLARIFIED], not\n                    [USER-APPROVED]. The distinction matters:\n                    [USER-APPROVED] marks places where the user trusted\n                    Claude's framing without verifying it.\n[USER-CLARIFIED]    user asked, Claude explained correctly, user\n                    accepted — no change needed\n[CLAUDE]            Claude produced this; user may not have verified\n[CLAUDE-UNPROMPTED] Claude did this without being asked, in a spot\n                    where asking first would have been appropriate.\n                    [CLAUDE-UNPROMPTED] is not the same as [CLAUDE].\n                    Use [CLAUDE] when Claude was asked to do something\n                    and did it. Use [CLAUDE-UNPROMPTED] only when Claude\n                    took an action without being directed to, in a spot\n                    where asking first would have been appropriate.\n                    When uncertain which applies, default to\n                    [CLAUDE-UNPROMPTED].\nFlag where confident framing by either party masked a wrong\nassumption or unclear scope. When confident framing masked a wrong\nassumption, identify the specific moment it happened: what was said,\nwhat assumption it smuggled in, and what the actual state was. Do not\nnote this as a general pattern — point to the exact turn. If you\ncannot point to a specific moment, do not include this flag.\n## Open Threads\nUnfinished work. For each item: state what was left incomplete, what\nthe concrete next action is, and what would need to be true for it to\nbe closed. Distinguish between (a) work deferred by explicit decision,\n(b) work that was discussed but never started, and (c) work that was\nassumed complete but wasn't verified. Do not list things that were\nresolved within the session.\nRules: expand acronyms on first use. Sub-agent calls count as\nClaude's work. When uncertain who proposed something, default to\n[CLAUDE].\n
`.trim();

/**
 * Calls the appropriate LLM provider to summarize a session transcript.
 * Handles LM Studio (lmstudio) and local llama-server (llama) providers.
 *
 * @param {string} transcript
 * @param {{ id: string, provider: string }} model
 * @param {object|null} registryEntry - llama registry entry (llama provider only)
 * @param {{ endpoint: string, modelId: string, stream: boolean }} opts - runtime config
 * @returns {Promise<{ summary: string, tps: number|null, ttft: number|null, genTime: number|null, completionTokens: number|null, promptTokens: number|null, reasoningTokens: number|null }>}
 */
export async function summarizeSession(transcript, model, registryEntry = null, opts = {}) {
  const { endpoint = "http://localhost:1234", modelId = model.id, stream = false, samplerOverrides = null } = opts;

  const useThinkingToken = /gem/i.test(model.id);
  const effectivePrompt = useThinkingToken
    ? SUMMARIZATION_PROMPT + "\n<|think|>"
    : SUMMARIZATION_PROMPT;

  if (model.provider === "lmstudio") {
    let response;
    try {
      response = await fetch(`${endpoint}/api/v0/chat/completions`, {
        method: "POST",
        signal: AbortSignal.timeout(30 * 60 * 1000),
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: model.id,
          messages: [
            { role: "system", content: effectivePrompt },
            { role: "user",   content: transcript },
          ],
          max_tokens: 8182,
          stream,
          ...(samplerOverrides ?? {}),
        }),
      });
    } catch (fetchErr) {
      throw new Error(`LM Studio fetch failed (${transcript.length} chars): ${fetchErr.message}`);
    }

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`LM Studio ${response.status} (${transcript.length} chars): ${body.slice(0, 300)}`);
    }

    if (stream) {
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
    const reasoning = (msg.reasoning_content ?? msg.reasoning ?? "").trim();

    let summary;
    if (!content && reasoning) {
      console.log("Received only reasoning block");
      summary = `\`\`\`reasoning-trace\n${reasoning}\n\`\`\``;
    } else if (content && reasoning) {
      console.log("Received both reasoning and content block");
      summary = `${content}\n\n---\n\n\`\`\`reasoning-trace\n${reasoning}\n\`\`\``;
    } else {
      console.log("Received only content block");
      summary = content;
    }

    return { summary, tps, ttft, genTime, completionTokens, promptTokens, reasoningTokens };
  }

  if (model.provider === "llama") {
    const resolved = registryEntry ? resolveLaunch(registryEntry) : { maxOutputTokens: 4096 };
    let response;
    const startMs = Date.now();
    const slotsPoller = setInterval(async () => {
      try {
        const r = await fetch(`http://localhost:${LLAMA_PORT}/slots`, { signal: AbortSignal.timeout(3000) });
        if (!r.ok) return;
        const slots = await r.json();
        const slot = Array.isArray(slots) ? slots[0] : null;
        if (!slot) return;
        const tok = slot.next_token?.[0]?.n_decoded ?? 0;
        const elapsed = ((Date.now() - startMs) / 1000).toFixed(1);
        const label = !slot.is_processing
          ? "idle"
          : tok === 0
            ? `prefilling… ${elapsed}s`
            : `prompt processed, generated ${tok} tok, elapsed ${elapsed}s`;
        process.stdout.write(`\r  ⟳ /slots: ${label}            `);
      } catch { /* ignore poll errors */ }
    }, 1000);
    try {
      response = await fetch(`http://localhost:${LLAMA_PORT}/v1/chat/completions`, {
        method: "POST",
        signal: AbortSignal.timeout(30 * 60 * 1000),
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: modelId,
          messages: [
            { role: "system", content: effectivePrompt },
            { role: "user",   content: transcript },
          ],
          max_tokens: resolved.maxOutputTokens,
          stream: false,
        }),
      });
    } catch (fetchErr) {
      clearInterval(slotsPoller);
      process.stdout.write("\n");
      throw new Error(`llama-server fetch failed (${transcript.length} chars): ${fetchErr.message}`);
    }
    clearInterval(slotsPoller);
    process.stdout.write("\n");

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`llama-server ${response.status} (${transcript.length} chars): ${body.slice(0, 300)}`);
    }

    const data = await response.json();
    fs.mkdirSync(LLAMA_RESPONSES_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(LLAMA_RESPONSES_DIR, `${Date.now()}--${modelId.replace(/[^a-zA-Z0-9-]/g, "-")}.json`),
      JSON.stringify(data, null, 2)
    );

    const msg = data.choices[0].message;
    let content = (msg.content ?? "").trim();
    let reasoning = (msg.reasoning_content ?? msg.reasoning ?? "").trim();

    // Gemma: reasoning tokens are inline in content, not in reasoning_content
    if (!reasoning && registryEntry?.reasoning) {
      const { startString, endString } = registryEntry.reasoning;
      const sIdx = content.indexOf(startString);
      const eIdx = content.indexOf(endString);
      if (sIdx !== -1 && eIdx !== -1) {
        reasoning = content.slice(sIdx + startString.length, eIdx).trim();
        content = content.slice(eIdx + endString.length).trim();
      }
    }
    content = content.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();

    const completionTokens = data.usage?.completion_tokens ?? null;
    const promptTokens = data.usage?.prompt_tokens ?? null;
    const tps     = data.timings?.predicted_per_second != null ? +data.timings.predicted_per_second.toFixed(2) : null;
    const ttft    = data.timings?.prompt_ms != null ? +(data.timings.prompt_ms / 1000).toFixed(4) : null;
    const genTime = data.timings?.predicted_ms != null ? +(data.timings.predicted_ms / 1000).toFixed(4) : null;
    const reasoningTokens = data.usage?.completion_tokens_details?.reasoning_tokens
      ?? (reasoning ? Math.round(reasoning.length / 4) : null);

    let summary;
    if (!content && reasoning) {
      console.log("Received only reasoning block");
      summary = `\`\`\`reasoning-trace\n${reasoning}\n\`\`\``;
    } else if (content && reasoning) {
      console.log("Received both reasoning and content block");
      summary = `${content}\n\n---\n\n\`\`\`reasoning-trace\n${reasoning}\n\`\`\``;
    } else {
      console.log("Received only content block");
      summary = content;
    }

    return { summary, tps, ttft, genTime, completionTokens, promptTokens, reasoningTokens };
  }

  throw new Error(`Unknown provider: ${model.provider}`);
}

/**
 * Uploads a summary to the Mem0 API.
 * @param {string} summary
 * @param {string} sessionId
 * @param {string} projectDir
 * @param {{ id: string, provider: string }} model
 * @param {{ apiKey: string, userId: string, infer: boolean, dryRun: boolean, noUpload: boolean }} opts
 */
export async function uploadToMem0(summary, sessionId, projectDir, model, opts = {}) {
  const { apiKey, userId, infer, dryRun = false, noUpload = false } = opts;

  if (dryRun) {
    console.log(`  [DRY-RUN] Would upload: user_id=${userId} infer=${infer}`);
    console.log(`    ${summary.slice(0, 200)}…`);
    return;
  }
  if (noUpload) return;

  const response = await fetch("https://api.mem0.ai/v1/memories/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Token ${apiKey}`,
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: summary }],
      user_id: userId,
      infer,
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

/**
 * Opens a per-run JSONL log file and returns a write/close handle.
 * @param {{ id: string }} model
 * @returns {{ write: (entry: object) => void, close: () => void, path: string }}
 */
export function openRunLog(model) {
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
