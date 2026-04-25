import fs from "fs";
import path from "path";
import { MEM0_DIR, TRANSCRIPTS_DIR } from "./paths.mjs";

/**
 * Returns the per-model state file path for the given model ID.
 * @param {string} modelId
 * @returns {string}
 */
export function stateFilePath(modelId) {
  const slug = modelId.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return path.join(MEM0_DIR, "state", `${slug}.json`);
}

/**
 * Loads the per-model state object. Returns {} if none exists.
 * @param {string} modelId
 * @returns {object}
 */
export function loadState(modelId) {
  const p = stateFilePath(modelId);
  if (!fs.existsSync(p)) return {};
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

/**
 * Persists the per-model state object to disk.
 * @param {object} state
 * @param {string} modelId
 */
export function saveState(state, modelId) {
  const p = stateFilePath(modelId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(state, null, 2));
}

/**
 * Returns the transcript cache file path for a session.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @returns {string}
 */
export function transcriptCachePath(sessionId, sessionSlug) {
  fs.mkdirSync(TRANSCRIPTS_DIR, { recursive: true });
  const prefix = sessionSlug ? `${sessionSlug}--${sessionId.slice(0, 8)}` : sessionId;
  return path.join(TRANSCRIPTS_DIR, `${prefix}.txt`);
}

/**
 * Loads a cached transcript. Returns null if none exists.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @returns {string|null}
 */
export function loadCachedTranscript(sessionId, sessionSlug) {
  const p = transcriptCachePath(sessionId, sessionSlug);
  if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
  return null;
}

/**
 * Writes a transcript to the cache.
 * @param {string} sessionId
 * @param {string|null} sessionSlug
 * @param {string} transcript
 */
export function saveCachedTranscript(sessionId, sessionSlug, transcript) {
  fs.writeFileSync(transcriptCachePath(sessionId, sessionSlug), transcript);
}
