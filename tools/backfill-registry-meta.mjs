#!/usr/bin/env node
// backfill-registry-meta.mjs
//
// One-shot script: reads all llama-server-*.log files, extracts model metadata,
// matches each log to a registry entry by its `path` field, and writes any
// missing metadata fields back to models-registry.json.
//
// Fill-missing semantics: existing registry values are never overwritten.
//
// Usage:
//   node backfill-registry-meta.mjs           # dry-run (prints changes, writes nothing)
//   node backfill-registry-meta.mjs --write   # applies changes

import fs from "fs";
import path from "path";
import os from "os";

const DRY_RUN = !process.argv.includes("--write");
const LOGS_DIR = path.join(os.homedir(), ".claude/mem0/logs");
const REGISTRY_PATH = path.join(
  os.homedir(),
  "Projects/mem0-processor/config/models-registry.json"
);
// Logs smaller than this are port-bind failures, not real loads
const MIN_LOG_BYTES = 3000;

// ─── PARSE META FROM LOG ─────────────────────────────────────────────────────

function parseLogMeta(text) {
  const find    = (re) => text.match(re)?.[1]?.trim() ?? null;
  const findInt = (re) => { const m = find(re); return m ? parseInt(m) : null; };

  // Model file path from the loader line
  const pathMatch = text.match(
    /^llama_model_loader: loaded meta data .+ from (.+?) \(version/m
  );
  if (!pathMatch) return null;

  // ─── EXISTING FIELDS ──────────────────────────────────────────────────────
  const nLayer      = findInt(/^print_info: n_layer\s+=\s+(\d+)/m);
  const nCtxTrain   = findInt(/^print_info: n_ctx_train\s+=\s+(\d+)/m);
  const modelType   = find(/^print_info: model type\s+=\s+(.+)/m);
  const modelParams = find(/^print_info: model params\s+=\s+(.+)/m);
  const quantType   = find(/^print_info: file type\s+=\s+(.+)/m);
  const bpw         = find(/^print_info: file size\s+=.+\((.+) BPW\)/m);

  const offloadMatch = text.match(/^load_tensors: offloaded (\d+)\/(\d+) layers to GPU/m);
  const kvMatch      = text.match(/^llama_kv_cache: size =\s+([\d.]+) MiB \(.*?(\d+) layers.*K \((\w+)\).*V \((\w+)\)/m);

  // ─── IDENTIFICATION ───────────────────────────────────────────────────────
  const modelName = find(/general\.name str\s+=\s+(.+)/m);
  const baseModel = find(/general\.base_model\.0\.name str\s+=\s+(.+)/m);
  const sizeLabel = find(/general\.size_label str\s+=\s+(.+)/m);

  // ─── ARCHITECTURE ─────────────────────────────────────────────────────────
  const architecture = find(/general\.architecture str\s+=\s+(\S+)/m);

  const expertMatch     = text.match(/(\w+)\.expert_count u32\s+=\s+(\d+)/m);
  const expertUsedMatch = text.match(/(\w+)\.expert_used_count u32\s+=\s+(\d+)/m);
  const expertCount     = expertMatch     ? parseInt(expertMatch[2])     : null;
  const expertUsedCount = expertUsedMatch ? parseInt(expertUsedMatch[2]) : null;

  // ─── ATTENTION MECHANICS ──────────────────────────────────────────────────
  const attentionHeads = findInt(/attention\.head_count u32\s+=\s+(\d+)/m);
  const kvHeads        = findInt(/attention\.head_count_kv u32\s+=\s+(\d+)/m);
  const gqaRatio       = (attentionHeads && kvHeads) ? attentionHeads / kvHeads : null;
  const hasSSM         = text.includes("ssm.conv_kernel");

  // ─── KV CACHE ─────────────────────────────────────────────────────────────
  const kvCacheSizeMiB = kvMatch ? parseFloat(kvMatch[1]) : null;
  const kvLayers       = kvMatch ? parseInt(kvMatch[2])   : null;
  const kvQuantK       = kvMatch?.[3] ?? null;
  const kvQuantV       = kvMatch?.[4] ?? null;

  // ─── MEMORY PROJECTION ────────────────────────────────────────────────────
  const projectedMatch      = text.match(/projected to use (\d+) MiB of device memory/m);
  const projectedMemoryMiB  = projectedMatch ? parseInt(projectedMatch[1]) : null;

  // ─── QUANTIZATION DETAILS ─────────────────────────────────────────────────
  const hasImatrix    = text.includes("quantize.imatrix.file");
  const imatrixEntries = hasImatrix ? findInt(/quantize\.imatrix\.entries_count u32\s+=\s+(\d+)/m) : null;

  const tensorLines = text.match(/llama_model_loader: - type\s+(\w+):\s+(\d+) tensors/g);
  let quantBreakdown     = null;
  let highPrecisionRatio = null;
  let ultraLowRatio      = null;
  let quantStrategy      = null;

  if (tensorLines) {
    const breakdown = {};
    let total = 0;
    for (const line of tensorLines) {
      const match = line.match(/type\s+(\w+):\s+(\d+)/);
      if (match) {
        breakdown[match[1]] = parseInt(match[2]);
        total += parseInt(match[2]);
      }
    }
    if (total > 0) {
      quantBreakdown = { ...breakdown, total };
      const highPrec = (breakdown.f32 || 0) + (breakdown.f16 || 0) + (breakdown.q8_0 || 0);
      const ultraLow = Object.keys(breakdown)
        .filter(k => k.startsWith("iq2"))
        .reduce((sum, k) => sum + breakdown[k], 0);
      highPrecisionRatio = highPrec / total;
      ultraLowRatio      = ultraLow / total;
      const numTypes = Object.keys(breakdown).length;
      if (numTypes === 1)          quantStrategy = "uniform";
      else if (numTypes >= 6)      quantStrategy = "highly_mixed";
      else if (highPrecisionRatio > 0.5) quantStrategy = "conservative";
      else                         quantStrategy = "aggressive";
    }
  }

  // ─── TRAINING DATASETS ────────────────────────────────────────────────────
  const datasetCountMatch = text.match(/general\.dataset\.count u32\s+=\s+(\d+)/);
  let datasets = null;
  if (datasetCountMatch) {
    const count = parseInt(datasetCountMatch[1]);
    datasets = [];
    for (let i = 0; i < count; i++) {
      const name = text.match(new RegExp(`general\\.dataset\\.${i}\\.name str\\s+=\\s+(.+)`, "m"))?.[1]?.trim() || null;
      const org  = text.match(new RegExp(`general\\.dataset\\.${i}\\.organization str\\s+=\\s+(.+)`, "m"))?.[1]?.trim() || null;
      if (name) datasets.push({ name, organization: org });
    }
    if (datasets.length === 0) datasets = null;
  }

  // ─── POSITIONAL ENCODING / SPECIAL ATTENTION ──────────────────────────────
  const ropeFreqBase    = find(/rope\.freq_base f32\s+=\s+([\d.e+-]+)/m);
  const specialAttention = architecture === "deepseek2" ? "MLA" : null;

  return {
    modelPath: pathMatch[1].trim(),
    nLayer, nCtxTrain, modelType, modelParams, quantType, bpw,
    offloadedLayers: offloadMatch ? parseInt(offloadMatch[1]) : null,
    totalLayers:     offloadMatch ? parseInt(offloadMatch[2]) : null,
    modelName, baseModel, sizeLabel,
    architecture, expertCount, expertUsedCount,
    attentionHeads, kvHeads, gqaRatio, hasSSM,
    kvCacheSizeMiB, kvLayers, kvQuantK, kvQuantV,
    projectedMemoryMiB,
    hasImatrix, imatrixEntries, quantBreakdown,
    highPrecisionRatio, ultraLowRatio, quantStrategy,
    datasets,
    ropeFreqBase, specialAttention,
  };
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────

const META_FIELDS = [
  "nLayer", "nCtxTrain", "modelType", "modelParams", "quantType", "bpw",
  "offloadedLayers", "totalLayers",
  "modelName", "baseModel", "sizeLabel",
  "architecture", "expertCount", "expertUsedCount",
  "attentionHeads", "kvHeads", "gqaRatio", "hasSSM",
  "kvCacheSizeMiB", "kvLayers", "kvQuantK", "kvQuantV",
  "projectedMemoryMiB",
  "hasImatrix", "imatrixEntries", "quantBreakdown",
  "highPrecisionRatio", "ultraLowRatio", "quantStrategy",
  "datasets",
  "ropeFreqBase", "specialAttention",
];

const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));

const pathToKey = {};
for (const [key, entry] of Object.entries(registry)) {
  if (entry.path) pathToKey[entry.path] = key;
}

const logFiles = fs
  .readdirSync(LOGS_DIR)
  .filter(f => f.startsWith("llama-server-") && f.endsWith(".log"))
  .sort()
  .reverse();

const metaByPath = {};
for (const file of logFiles) {
  const fullPath = path.join(LOGS_DIR, file);
  if (fs.statSync(fullPath).size < MIN_LOG_BYTES) continue;
  let text;
  try { text = fs.readFileSync(fullPath, "utf8"); } catch { continue; }
  const meta = parseLogMeta(text);
  if (!meta) continue;
  if (!metaByPath[meta.modelPath]) metaByPath[meta.modelPath] = meta;
}

// ─── APPLY TO REGISTRY ────────────────────────────────────────────────────────

const updates = {};

for (const [modelPath, meta] of Object.entries(metaByPath)) {
  const regKey = pathToKey[modelPath];
  if (!regKey) {
    console.log(`  UNMATCHED  ${modelPath}`);
    continue;
  }

  const entry = registry[regKey];
  const toWrite = {};

  for (const field of META_FIELDS) {
    if (meta[field] == null) continue;
    if (entry[field] != null) continue;  // fill-missing: skip if already set
    toWrite[field] = meta[field];
  }

  if (Object.keys(toWrite).length > 0) updates[regKey] = toWrite;
}

// ─── REPORT ───────────────────────────────────────────────────────────────────

if (Object.keys(updates).length === 0) {
  console.log("No missing fields found — registry is up to date.");
  process.exit(0);
}

for (const [key, fields] of Object.entries(updates)) {
  console.log(`  ${key}`);
  for (const [f, v] of Object.entries(fields)) {
    const display = typeof v === "object" ? JSON.stringify(v) : v;
    console.log(`    ${f}: ${display}`);
  }
}

if (DRY_RUN) {
  console.log(`\nDry run — ${Object.keys(updates).length} entries would be updated. Pass --write to apply.`);
  process.exit(0);
}

for (const [key, fields] of Object.entries(updates)) {
  Object.assign(registry[key], fields);
}

fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
console.log(`\nWrote ${Object.keys(updates).length} updated entries to ${REGISTRY_PATH}`);