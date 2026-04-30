import fs from "fs";
import path from "path";
import { PERF_STORE_PATH } from "./paths.mjs";

/**
 * Loads the perf store from disk. Returns {} if the file doesn't exist.
 * @returns {object}
 */
export function loadPerfStore() {
  if (!fs.existsSync(PERF_STORE_PATH)) return {};
  return JSON.parse(fs.readFileSync(PERF_STORE_PATH, "utf8"));
}

/**
 * Persists the in-memory perf store to disk.
 * @param {object} store
 */
export function savePerfStore(store) {
  fs.mkdirSync(path.dirname(PERF_STORE_PATH), { recursive: true });
  fs.writeFileSync(PERF_STORE_PATH, JSON.stringify(store, null, 2));
}

/**
 * Appends one perf entry for modelId and flushes to disk.
 * @param {object} store - In-memory perf store (mutated in place).
 * @param {string} modelId
 * @param {object} entry
 */
export function appendPerfEntry(store, modelId, entry) {
  if (!store[modelId]) store[modelId] = { runs: [] };
  store[modelId].runs.push(entry);
  savePerfStore(store);
}

/**
 * Heuristically classifies whether a cache hit occurred for the current run.
 * Uses prefill speed and a token-count match against recent runs in the perf store.
 * @param {object} perfStore
 * @param {string} modelId
 * @param {{ promptTokens: number|null, ttft: number|null }} params
 * @returns {'definite'|'likely'|'possible'|'none'|'unknown'}
 */
export function classifyCacheHit(perfStore, modelId, { promptTokens, ttft }) {
  if (!promptTokens || !ttft) return 'unknown';
  const prefillTps = promptTokens / ttft;

  const recentRuns = (perfStore[modelId]?.runs ?? [])
    .filter(r => !r.failed && r.promptTokens && r.ts)
    .slice(-20);

  const WINDOW_MS = 30 * 60 * 1000;
  const matchingRun = recentRuns.find(r =>
    r.promptTokens === promptTokens &&
    (Date.now() - new Date(r.ts)) < WINDOW_MS
  );

  if (prefillTps > 2000 && matchingRun) return 'definite';
  if (prefillTps > 1500 && matchingRun) return 'likely';
  if (prefillTps > 2000) return 'likely';
  if (prefillTps > 800 && matchingRun) return 'possible';
  return 'none';
}

/**
 * Builds a normalized perf entry object from run-time state. Shared by the success
 * and error paths in main() to keep the perf store schema consistent.
 *
 * Pass failed=true and failReason/runtime for error-path entries.
 *
 * @param {{
 *   stateKey: string,
 *   runTag: string|null,
 *   idleGb: number|null,
 *   preSessionIdleGb: number|null,
 *   postSessionIdleGb: number|null,
 *   idleSwap: number|null,
 *   postSessionSwap: number|null,
 *   idleMemPressure: number|null,
 *   noModelGb: number|null,
 *   noModelSwap: number|null,
 *   noModelPressure: number|null,
 *   peakUsedGb: number|null,
 *   avgUsedGb: number|null,
 *   startingSwap: number|null,
 *   maxSwap: number|null,
 *   avgSwap: number|null,
 *   peakPressure: number|null,
 *   pressureAvg: number|null,
 *   ttft: number|null,
 *   genTime: number|null,
 *   tps: number|null,
 *   prefillTps: number|null,
 *   promptTokens: number|null,
 *   completionTokens: number|null,
 *   reasoningTokens: number|null,
 *   transcriptChars: number|null,
 *   effectiveMaxChars: number|null,
 *   cacheHit: string|null,
 *   batchIndex: number|null,
 *   timeSinceLastRunMin: number|null,
 *   modelLoadMs: number|null,
 *   modelInfo: object|null,
 *   llamaRegistryEntry: object|null,
 *   resolved: object|null,
 *   failed?: boolean,
 *   failReason?: string|null,
 *   runtime?: number|null,
 * }} params
 * @returns {object}
 */
export function buildPerfEntry({
  stateKey, runTag,
  idleGb, preSessionIdleGb, postSessionIdleGb, idleSwap, postSessionSwap, idleMemPressure,
  noModelGb, noModelSwap, noModelPressure,
  peakUsedGb, avgUsedGb, startingSwap, maxSwap, avgSwap, peakPressure, pressureAvg,
  ttft, genTime, tps, prefillTps,
  promptTokens, completionTokens, reasoningTokens,
  transcriptChars, effectiveMaxChars, cacheHit,
  batchIndex, timeSinceLastRunMin, modelLoadMs,
  modelInfo, llamaRegistryEntry, resolved,
  failed = false, failReason = null, runtime = null,
}) {
  return {
    ts:                  new Date().toISOString(),
    session:             stateKey,
    runTag,
    idleGb,
    preSessionIdleGb:    preSessionIdleGb ?? null,
    postSessionIdleGb:   postSessionIdleGb ?? null,
    idleSwap,
    postSessionSwap:     postSessionSwap ?? null,
    idleMemPressure,
    noModelGb,
    noModelSwap,
    noModelPressure,
    peakGb:              peakUsedGb,
    avgGb:               avgUsedGb,
    ttft:                ttft ?? null,
    genTime:             genTime ?? null,
    runtime:             runtime ?? null,
    promptTokens:        promptTokens ?? null,
    loadedContextChars:  effectiveMaxChars,
    startingSwap:        startingSwap ?? null,
    maxSwap:             maxSwap ?? null,
    avgSwap:             avgSwap ?? null,
    peakPressure:        peakPressure ?? null,
    pressureAvg:         pressureAvg ?? null,
    tps:                 tps ?? null,
    prefillTps:          prefillTps ?? null,
    ctxSize:             modelInfo?.loaded_context_length ?? llamaRegistryEntry?.launch?.ctxSize ?? null,
    completionTokens:    completionTokens ?? null,
    reasoningTokens:     reasoningTokens ?? null,
    transcriptChars:     transcriptChars ?? null,
    cacheHit,
    runIndexInBatch:     batchIndex,
    timeSinceLastRunMin,
    modelLoadMs,
    launchParams:        llamaRegistryEntry?.launch ?? null,
    arch:                llamaRegistryEntry?.arch ?? null,
    fileSizeGb:          llamaRegistryEntry?.fileSizeGb ?? null,
    kvBytesPerToken:     llamaRegistryEntry?.kvBytesPerToken ?? null,
    kvQuantK:            resolved?.kvQuantK ?? null,
    kvQuantV:            resolved?.kvQuantV ?? null,
    minP:                resolved?.sampler.minP ?? null,
    temp:                resolved?.sampler.temp ?? null,
    topK:                resolved?.sampler.topK ?? null,
    topP:                resolved?.sampler.topP ?? null,
    maxOutputTokens:     resolved?.maxOutputTokens ?? null,
    nExpertsUsed:        llamaRegistryEntry?.launch?.nExpertsUsed ?? null,
    nGpuLayers:          llamaRegistryEntry?.launch?.nGpuLayers ?? null,
    ...(failed ? { failed, failReason } : {}),
  };
}
