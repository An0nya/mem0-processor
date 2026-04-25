import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import { LLAMA_REGISTRY_PATH, LOGS_DIR } from "./paths.mjs";
import { LLAMA_PORT, loadLlamaRegistry, buildLlamaFlags } from "./registry.mjs";

let _llamaProc = null;

/**
 * Registers SIGINT/SIGTERM/exit handlers to ensure llama-server is killed on process exit.
 * Call once at startup before launching any server.
 */
export function registerSignalHandlers() {
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => {
      if (_llamaProc) { _llamaProc.kill("SIGTERM"); }
      process.exit(sig === "SIGINT" ? 130 : 143);
    });
  }
  process.on("exit", () => { if (_llamaProc) _llamaProc.kill("SIGTERM"); });
}

/**
 * Fetches model info from the LM Studio v0 API.
 * @param {string} modelId
 * @param {string} endpoint - LM Studio base URL
 * @returns {Promise<object|null>}
 */
export async function getModelInfo(modelId, endpoint) {
  try {
    const res = await fetch(`${endpoint}/api/v0/models/${encodeURIComponent(modelId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Launches llama-server for the given registry model ID. Waits until /health returns ok,
 * then parses the log for metadata and backfills the registry. Returns run context.
 * @param {string} modelId
 * @returns {Promise<{ proc: ChildProcess, modelLoadMs: number, logFile: string, entry: object, isEarlyExit: () => boolean }>}
 */
export async function launchLlamaServer(modelId) {
  const registry = loadLlamaRegistry();
  const entry = registry[modelId];
  if (!entry) {
    const available = Object.keys(registry).join(", ");
    throw new Error(`Model "${modelId}" not in registry. Available: ${available}`);
  }

  const flags = buildLlamaFlags(entry);
  console.log(`  Spawning llama-server: ${modelId}`);
  console.log(`  Flags: llama-server ${flags.join(" ")}\n`);

  const proc = spawn("llama-server", flags, { stdio: ["ignore", "pipe", "pipe"] });
  _llamaProc = proc;

  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const logFile = path.join(LOGS_DIR, `llama-server-${Date.now()}.log`);
  const logStream = fs.createWriteStream(logFile, { flags: "a" });
  proc.stdout.pipe(logStream);
  proc.stderr.pipe(logStream);

  let earlyExit = false;
  proc.on("error", (err) => { console.error(`  llama-server error: ${err.message}`); });
  proc.on("exit", (code) => { if (code !== null) earlyExit = true; });

  const launchStartMs = Date.now();
  const HEALTH_URL = `http://localhost:${LLAMA_PORT}/health`;
  const TIMEOUT_MS = 5 * 60 * 1000;

  await new Promise((resolve, reject) => {
    const deadline = Date.now() + TIMEOUT_MS;
    const poll = async () => {
      if (earlyExit) { reject(new Error("llama-server exited before becoming healthy")); return; }
      if (Date.now() > deadline) { reject(new Error("llama-server health check timed out after 5 minutes")); return; }
      try {
        const res = await fetch(HEALTH_URL);
        const body = await res.json();
        if (body.status === "ok") { resolve(); return; }
      } catch { /* not ready yet */ }
      setTimeout(poll, 1000);
    };
    setTimeout(poll, 1000);
  });

  const modelLoadMs = Date.now() - launchStartMs;
  const meta = parseModelMeta(logFile);
  console.log(`  llama-server ready in ${(modelLoadMs / 1000).toFixed(1)}s  (log: ${logFile})`);
  if (meta) {
    const offload = meta.offloadedLayers != null ? `${meta.offloadedLayers}/${meta.totalLayers}` : `?/${meta.nLayer ?? "?"}`;
    const kv = meta.kvCacheSizeMiB != null ? `${meta.kvCacheSizeMiB} MiB` : null;
    const kvDetail = (meta.kvLayers != null && meta.kvQuantK) ? ` (${meta.kvLayers} attn layers, ${meta.kvQuantK}${meta.kvQuantK !== meta.kvQuantV ? `/${meta.kvQuantV}` : ""})` : "";
    console.log(`  ${meta.modelType ?? "?"}  ${meta.modelParams ?? "?"}  ${meta.quantType ?? "?"}${meta.bpw ? ` (${meta.bpw} BPW)` : ""}`);
    console.log(`  Layers: ${meta.nLayer ?? "?"} total, ${offload} on GPU`);
    if (kv) console.log(`  KV cache: ${kv}${kvDetail}`);
    console.log(`  Context: ${entry.launch.ctxSize.toLocaleString()} / ${meta.nCtxTrain?.toLocaleString() ?? "?"} trained`);
  }
  console.log();

  if (meta) {
    const META_FIELDS = [
      "nLayer", "nCtxTrain", "modelType", "modelParams", "quantType", "bpw",
      "offloadedLayers", "totalLayers", "kvLayers",
      "modelName", "baseModel", "sizeLabel",
      "architecture", "expertCount", "expertUsedCount",
      "attentionHeads", "kvHeads", "gqaRatio", "hasSSM",
      "kvCacheSizeMiB", "kvQuantK", "kvQuantV",
      "projectedMemoryMiB",
      "hasImatrix", "imatrixEntries", "quantBreakdown",
      "highPrecisionRatio", "ultraLowRatio", "quantStrategy",
      "datasets",
      "ropeFreqBase", "specialAttention",
    ];
    let wrote = false;
    for (const f of META_FIELDS) {
      if (meta[f] == null) continue;
      if (entry[f] != null && entry[f] !== meta[f]) {
        console.warn(`  [registry] ${modelId}.${f}: registry=${entry[f]} log=${meta[f]} — log wins`);
      }
      entry[f] = meta[f];
      wrote = true;
    }
    if (wrote) fs.writeFileSync(LLAMA_REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
  }

  return { proc, modelLoadMs, logFile, entry, isEarlyExit: () => earlyExit };
}

/**
 * Parses a llama-server log file for model metadata.
 * @param {string} logFile
 * @returns {object|null}
 */
export function parseModelMeta(logFile) {
  let text;
  try { text = fs.readFileSync(logFile, "utf8"); } catch { return null; }

  const find = (re) => text.match(re)?.[1]?.trim() ?? null;
  const findInt = (re) => { const m = find(re); return m ? parseInt(m) : null; };

  // ─── EXISTING FIELDS ────────────────────────────────────────────────
  const nLayer     = findInt(/^print_info: n_layer\s+=\s+(\d+)/m);
  const nCtxTrain  = findInt(/^print_info: n_ctx_train\s+=\s+(\d+)/m);
  const modelType  = find(/^print_info: model type\s+=\s+(.+)/m);
  const modelParams = find(/^print_info: model params\s+=\s+(.+)/m);
  const quantType  = find(/^print_info: file type\s+=\s+(.+)/m);
  const bpw        = find(/^print_info: file size\s+=.+\((.+) BPW\)/m);

  const offloadMatch = text.match(/^load_tensors: offloaded (\d+)\/(\d+) layers to GPU/m);
  const kvMatch = text.match(/^llama_kv_cache: size =\s+([\d.]+) MiB \(.*?(\d+) layers.*K \((\w+)\).*V \((\w+)\)/m);

  // ─── IDENTIFICATION ─────────────────────────────────────────────────
  const modelName  = find(/general\.name str\s+=\s+(.+)/m);
  const baseModel  = find(/general\.base_model\.0\.name str\s+=\s+(.+)/m);
  const sizeLabel  = find(/general\.size_label str\s+=\s+(.+)/m);

  // ─── ARCHITECTURE ───────────────────────────────────────────────────
  const architecture = find(/general\.architecture str\s+=\s+(\S+)/m);

  const expertMatch = text.match(/(\w+)\.expert_count u32\s+=\s+(\d+)/m);
  const expertUsedMatch = text.match(/(\w+)\.expert_used_count u32\s+=\s+(\d+)/m);
  const expertCount = expertMatch ? parseInt(expertMatch[2]) : null;
  const expertUsedCount = expertUsedMatch ? parseInt(expertUsedMatch[2]) : null;

  // ─── ATTENTION MECHANICS ────────────────────────────────────────────
  const attentionHeads = findInt(/attention\.head_count u32\s+=\s+(\d+)/m);
  const kvHeads = findInt(/attention\.head_count_kv u32\s+=\s+(\d+)/m);
  const gqaRatio = (attentionHeads && kvHeads) ? attentionHeads / kvHeads : null;

  const hasSSM = text.includes('ssm.conv_kernel');

  // ─── KV CACHE ───────────────────────────────────────────────────────
  const kvCacheSizeMiB = kvMatch ? parseFloat(kvMatch[1]) : null;
  const kvQuantK = kvMatch?.[3] ?? null;
  const kvQuantV = kvMatch?.[4] ?? null;

  // ─── MEMORY PROJECTION ──────────────────────────────────────────────
  const projectedMatch = text.match(/projected to use (\d+) MiB of device memory/m);
  const projectedMemoryMiB = projectedMatch ? parseInt(projectedMatch[1]) : null;

  // ─── QUANTIZATION DETAILS ───────────────────────────────────────────
  const hasImatrix = text.includes('quantize.imatrix.file');
  const imatrixEntries = hasImatrix ? findInt(/quantize\.imatrix\.entries_count u32\s+=\s+(\d+)/m) : null;

  const tensorLines = text.match(/llama_model_loader: - type\s+(\w+):\s+(\d+) tensors/g);
  let quantBreakdown = null;
  let highPrecisionRatio = null;
  let ultraLowRatio = null;
  let quantStrategy = null;

  if (tensorLines) {
    const breakdown = {};
    let total = 0;

    for (const line of tensorLines) {
      const match = line.match(/type\s+(\w+):\s+(\d+)/);
      if (match) {
        const [, type, count] = match;
        breakdown[type] = parseInt(count);
        total += parseInt(count);
      }
    }

    if (total > 0) {
      quantBreakdown = { ...breakdown, total };
      const highPrec = (breakdown.f32 || 0) + (breakdown.f16 || 0) + (breakdown.q8_0 || 0);
      const ultraLow = Object.keys(breakdown)
        .filter(k => k.startsWith('iq2'))
        .reduce((sum, k) => sum + breakdown[k], 0);
      highPrecisionRatio = highPrec / total;
      ultraLowRatio = ultraLow / total;
      const numTypes = Object.keys(breakdown).length;
      if (numTypes === 1) quantStrategy = "uniform";
      else if (numTypes >= 6) quantStrategy = "highly_mixed";
      else if (highPrecisionRatio > 0.5) quantStrategy = "conservative";
      else quantStrategy = "aggressive";
    }
  }

  // ─── TRAINING DATASETS ──────────────────────────────────────────────
  const datasetCountMatch = text.match(/general\.dataset\.count u32\s+=\s+(\d+)/);
  let datasets = null;

  if (datasetCountMatch) {
    const count = parseInt(datasetCountMatch[1]);
    datasets = [];
    for (let i = 0; i < count; i++) {
      const nameRe = new RegExp(`general\\.dataset\\.${i}\\.name str\\s+=\\s+(.+)`, 'm');
      const orgRe = new RegExp(`general\\.dataset\\.${i}\\.organization str\\s+=\\s+(.+)`, 'm');
      const name = text.match(nameRe)?.[1]?.trim() || null;
      const org = text.match(orgRe)?.[1]?.trim() || null;
      if (name) datasets.push({ name, organization: org });
    }
    if (datasets.length === 0) datasets = null;
  }

  // ─── POSITIONAL ENCODING ────────────────────────────────────────────
  const ropeFreqBase = find(/rope\.freq_base f32\s+=\s+([\d.e+-]+)/m);

  // ─── SPECIAL ATTENTION ──────────────────────────────────────────────
  const specialAttention = architecture === "deepseek2" ? "MLA" : null;

  return {
    nLayer, nCtxTrain, modelType, modelParams, quantType, bpw,
    offloadedLayers: offloadMatch ? parseInt(offloadMatch[1]) : null,
    totalLayers: offloadMatch ? parseInt(offloadMatch[2]) : null,
    modelName, baseModel, sizeLabel,
    architecture, expertCount, expertUsedCount,
    attentionHeads, kvHeads, gqaRatio, hasSSM,
    kvCacheSizeMiB,
    kvLayers: kvMatch ? parseInt(kvMatch[2]) : null,
    kvQuantK, kvQuantV,
    projectedMemoryMiB,
    hasImatrix, imatrixEntries, quantBreakdown,
    highPrecisionRatio, ultraLowRatio, quantStrategy,
    datasets,
    ropeFreqBase,
    specialAttention,
  };
}

/**
 * Sends SIGTERM to the llama-server process.
 * @param {ChildProcess} proc
 */
export function shutdownLlamaServer(proc) {
  if (!proc) return;
  console.log("  Shutting down llama-server…");
  proc.kill("SIGTERM");
}