import fs from "fs";
import path from "path";
import { PROJECTS_DIR, COMPACTION_SUMMARIES_DIR } from "./paths.mjs";

/**
 * Scans the Claude projects directory and returns all session JSONL files.
 * @returns {{ sessionId: string, projectDir: string, filePath: string }[]}
 */
export function findSessions() {
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

/**
 * Reads and parses a session JSONL file into an array of entry objects.
 * Deduplicates by UUID to strip re-appended entries from VSCode session reopens.
 * @param {string} filePath
 * @returns {object[]}
 */
export function parseSession(filePath) {
  const seen = new Set();
  return fs
    .readFileSync(filePath, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean)
    .filter((e) => {
      if (!e.uuid) return true;
      if (seen.has(e.uuid)) return false;
      seen.add(e.uuid);
      return true;
    });
}

/**
 * Returns the slug from the first JSONL entry that has one, or null.
 * @param {string} filePath
 * @returns {string|null}
 */
export function extractSessionSlug(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").split("\n");
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.slug) return entry.slug;
    } catch { /* skip */ }
  }
  return null;
}

/**
 * Returns the timestamp from the first entry in the file (scans up to 30 lines), or null.
 * @param {string} filePath
 * @returns {string|null}
 */
export function extractSessionStartTime(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").split("\n");
  for (const line of lines.slice(0, 30)) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.timestamp) return entry.timestamp;
    } catch { /* skip */ }
  }
  return null;
}

/**
 * Extracts typed content blocks from a session entry. Returns null if the entry
 * has no recognizable content shape.
 * @param {object} entry
 * @returns {{ blocks: object[]|string, entryType: string, model: string|null }|null}
 */
export function extractContentBlocks(entry) {
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

export const TRANSCRIPT_LEGEND = "[TRANSCRIPT FORMAT: TOOL_AUTO = no user approval required OR user approved action type globally previously; TOOL_DENIED = user explicitly rejected; TOOL_ERROR = execution failed; TOOL_CALL/TOOL_RESULT = standard supervised tool use; THINKING = model extended reasoning trace]";

/**
 * Builds a human-readable transcript string from session entries.
 * @param {object[]} entries
 * @param {number} [toolResultMaxChars=1000]
 * @returns {string}
 */
export function buildTranscript(entries, toolResultMaxChars = 1000) {
  // Pre-pass: detect auto-approved tools (tool_use in assistant entry immediately followed
  // by matching tool_result in next user entry, no other user entry in between).
  const autoApprovedIds = new Set();
  let pendingToolUseIds = new Set();
  for (const entry of entries) {
    const extracted = extractContentBlocks(entry);
    if (!extracted) continue;
    if (extracted.entryType === "assistant") {
      pendingToolUseIds = new Set();
      for (const block of extracted.blocks) {
        if (block.type === "tool_use" && block.id) pendingToolUseIds.add(block.id);
      }
    } else if (extracted.entryType === "user") {
      if (pendingToolUseIds.size > 0) {
        for (const block of extracted.blocks) {
          if (block.type === "tool_result" && pendingToolUseIds.has(block.tool_use_id)) {
            autoApprovedIds.add(block.tool_use_id);
          }
        }
      }
      pendingToolUseIds = new Set();
    }
  }

  const lines = [TRANSCRIPT_LEGEND];

  for (const entry of entries) {
    const extracted = extractContentBlocks(entry);
    if (!extracted) continue;
    const { blocks, entryType, model } = extracted;
    const isSubAgent = !!entry.data?.message?.message;
    const agentTag = isSubAgent ? ` (sub-agent: ${model})` : "";

    for (const block of blocks) {
      if (block.type === "thinking") {
        lines.push(`[THINKING]\n${block.thinking}\n[/THINKING]`);
        continue;
      }
      if (block.type === "text") {
        lines.push(`[${entryType === "user" ? "USER" : "ASSISTANT"}${agentTag}] ${block.text}`);
      } else if (block.type === "tool_use") {
        lines.push(`[TOOL_CALL${agentTag}] ${block.name}(${JSON.stringify(block.input).slice(0, 300)})`);
      } else if (block.type === "tool_result") {
        const raw = typeof block.content === "string" ? block.content : JSON.stringify(block.content);
        if (raw.includes("<persisted-output>")) {
          const sizeMatch = raw.match(/Output too large \([\d.]+KB\)/);
          lines.push(`[TOOL_RESULT${agentTag}] ${sizeMatch?.[0] || "Large output"} — persisted to disk`);
        } else if (block.is_error && raw.includes("The user doesn't want to proceed with this tool use")) {
          const reasonMatch = raw.match(/The user provided the following reason for the rejection:\s*([\s\S]*)/);
          const reason = reasonMatch ? reasonMatch[1].trim() : null;
          lines.push(`[TOOL_DENIED${agentTag}]${reason ? `: ${reason}` : ""}`);
        } else {
          const isAuto = autoApprovedIds.has(block.tool_use_id);
          lines.push(`[${block.is_error ? "TOOL_ERROR" : isAuto ? "TOOL_AUTO" : "TOOL_RESULT"}${agentTag}] ${raw.slice(0, toolResultMaxChars)}`);
        }
      }
    }
  }

  return lines.join("\n");
}

/**
 * Walks entries for compact_boundary → isCompactSummary pairs, writes each to
 * COMPACTION_SUMMARIES_DIR. Returns array of compaction summary records.
 * @param {string} sessionId
 * @param {object[]} entries
 * @returns {{ compactIndex: number, boundaryIndex: number, timestamp: string|null, summary: string, cachePath: string }[]}
 */
export function extractAndCacheCompactionSummaries(sessionId, entries) {
  const results = [];
  let compactIndex = 0;
  for (let i = 0; i < entries.length - 1; i++) {
    const e = entries[i];
    if (e.type === "system" && e.subtype === "compact_boundary") {
      const next = entries[i + 1];
      if (next?.isCompactSummary === true) {
        const extracted = extractContentBlocks(next);
        let summaryText = null;
        if (extracted) {
          if (typeof extracted.blocks === "string") {
            summaryText = extracted.blocks.trim();
          } else {
            summaryText = extracted.blocks
              .filter(b => b.type === "text")
              .map(b => b.text ?? "")
              .join("\n")
              .trim();
          }
        }
        if (summaryText) {
          fs.mkdirSync(COMPACTION_SUMMARIES_DIR, { recursive: true });
          const cachePath = path.join(COMPACTION_SUMMARIES_DIR, `${sessionId}-${compactIndex}.md`);
          fs.writeFileSync(cachePath, summaryText);
          results.push({ compactIndex, boundaryIndex: i, timestamp: e.timestamp ?? null, summary: summaryText, cachePath });
        }
        compactIndex++;
      }
    }
  }
  return results;
}

/**
 * Splits entries at compaction boundaries into processable segments.
 * When compactionSummaries is empty, returns a single whole-session segment (partSuffix = "").
 * @param {object[]} entries
 * @param {object[]} compactionSummaries
 * @returns {{ entries: object[], partSuffix: string, priorContext: string|null, startTimestamp: string|null, endTimestamp: string|null }[]}
 */
export function buildSegments(entries, compactionSummaries) {
  if (compactionSummaries.length === 0) {
    return [{ entries, partSuffix: "", priorContext: null, startTimestamp: null, endTimestamp: null }];
  }
  const segments = [];
  let segStart = 0;
  for (let ci = 0; ci < compactionSummaries.length; ci++) {
    const boundary = compactionSummaries[ci];
    segments.push({
      entries: entries.slice(segStart, boundary.boundaryIndex),
      partSuffix: `-part${ci}`,
      priorContext: ci === 0 ? null : compactionSummaries[ci - 1].summary,
      startTimestamp: ci === 0 ? null : compactionSummaries[ci - 1].timestamp,
      endTimestamp: boundary.timestamp,
    });
    segStart = boundary.boundaryIndex + 2; // skip compact_boundary + isCompactSummary entries
  }
  const last = compactionSummaries[compactionSummaries.length - 1];
  segments.push({
    entries: entries.slice(segStart),
    partSuffix: `-part${compactionSummaries.length}`,
    priorContext: last.summary,
    startTimestamp: last.timestamp,
    endTimestamp: null,
  });
  return segments;
}

/** Max chars for a transcript to be eligible for merge into a group. */
export const MERGE_CHAR_THRESHOLD = 2000;
/** Max gap between sessions to still merge them into a single process unit. */
export const MERGE_GAP_MS = 15 * 60 * 1000;

/**
 * Groups transcript records into solo or merged process units.
 * Merge eligibility: transcript ≤ MERGE_CHAR_THRESHOLD chars, no priorContext,
 * same projectDir, and gap ≤ MERGE_GAP_MS between sessions.
 * @param {object[]} records
 * @returns {{ type: 'solo'|'merged', records: object[] }[]}
 */
export function buildProcessUnits(records) {
  const units = [];
  let i = 0;
  while (i < records.length) {
    const r = records[i];
    const eligible = r.transcript.length <= MERGE_CHAR_THRESHOLD && r.seg.priorContext === null;
    if (!eligible) {
      units.push({ type: "solo", records: [r] });
      i++;
      continue;
    }
    const group = [r];
    let j = i + 1;
    while (j < records.length) {
      const next = records[j];
      if (next.session.projectDir !== r.session.projectDir) break;
      if (next.transcript.length > MERGE_CHAR_THRESHOLD || next.seg.priorContext !== null) break;
      const prevEnd   = group[group.length - 1].endedAt;
      const nextStart = next.startedAt;
      if (prevEnd && nextStart) {
        const gapMs = new Date(nextStart) - new Date(prevEnd);
        if (gapMs > MERGE_GAP_MS) break;
      }
      group.push(next);
      j++;
    }
    units.push({ type: group.length === 1 ? "solo" : "merged", records: group });
    i = j;
  }
  return units;
}
