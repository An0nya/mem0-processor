#!/usr/bin/env node
// backfill-registry-meta.mjs
//
// One-shot script: reads all llama-server-*.log files, extracts model metadata,
// matches each log to a registry entry by its `path` field, and writes any
// missing metadata fields back to models-registry.json.
//
// Fields written (only if absent or null in the registry):
//   nLayer, nCtxTrain, modelType, modelParams, quantType, bpw
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
  const find = (re) => text.match(re)?.[1]?.trim() ?? null;

  // Model file path from the loader line
  const pathMatch = text.match(
    /^llama_model_loader: loaded meta data .+ from (.+?) \(version/m
  );

  const nLayer    = find(/^print_info: n_layer\s+=\s+(\d+)/m);
  const nCtxTrain = find(/^print_info: n_ctx_train\s+=\s+(\d+)/m);
  const modelType = find(/^print_info: model type\s+=\s+(.+)/m);
  const modelParams = find(/^print_info: model params\s+=\s+(.+)/m);
  const quantType = find(/^print_info: file type\s+=\s+(.+)/m);
  const bpw       = find(/^print_info: file size\s+=.+\((.+) BPW\)/m);

  if (!pathMatch) return null;

  return {
    modelPath:   pathMatch[1].trim(),
    nLayer:      nLayer    ? +nLayer    : null,
    nCtxTrain:   nCtxTrain ? +nCtxTrain : null,
    modelType,
    modelParams,
    quantType,
    bpw,
  };
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));

// Build a reverse map: modelPath → registryKey
const pathToKey = {};
for (const [key, entry] of Object.entries(registry)) {
  if (entry.path) pathToKey[entry.path] = key;
}

// Scan logs, newest first; one entry per model path (most recent wins)
const logFiles = fs
  .readdirSync(LOGS_DIR)
  .filter((f) => f.startsWith("llama-server-") && f.endsWith(".log"))
  .sort()
  .reverse();

const metaByPath = {};

for (const file of logFiles) {
  const fullPath = path.join(LOGS_DIR, file);
  const stat = fs.statSync(fullPath);
  if (stat.size < MIN_LOG_BYTES) continue;

  let text;
  try { text = fs.readFileSync(fullPath, "utf8"); } catch { continue; }

  const meta = parseLogMeta(text);
  if (!meta) continue;

  // First log we see is newest (we sorted desc); don't overwrite
  if (!metaByPath[meta.modelPath]) metaByPath[meta.modelPath] = meta;
}

// ─── APPLY TO REGISTRY ───────────────────────────────────────────────────────

const META_FIELDS = ["nLayer", "nCtxTrain", "modelType", "modelParams", "quantType", "bpw"];
const updates = {};

for (const [modelPath, meta] of Object.entries(metaByPath)) {
  const regKey = pathToKey[modelPath];
  if (!regKey) {
    console.log(`  UNMATCHED  ${modelPath}`);
    continue;
  }

  const entry = registry[regKey];
  const missing = META_FIELDS.filter((f) => entry[f] == null);
  if (missing.length === 0) continue;

  updates[regKey] = {};
  for (const field of missing) {
    if (meta[field] != null) updates[regKey][field] = meta[field];
  }

  if (Object.keys(updates[regKey]).length === 0) {
    delete updates[regKey];
  }
}

// ─── REPORT ──────────────────────────────────────────────────────────────────

if (Object.keys(updates).length === 0) {
  console.log("No missing fields found — registry is up to date.");
  process.exit(0);
}

for (const [key, fields] of Object.entries(updates)) {
  console.log(`  ${key}`);
  for (const [f, v] of Object.entries(fields)) {
    console.log(`    ${f}: ${v}`);
  }
}

if (DRY_RUN) {
  console.log(`\nDry run — ${Object.keys(updates).length} entries would be updated. Pass --write to apply.`);
  process.exit(0);
}

// Apply
for (const [key, fields] of Object.entries(updates)) {
  Object.assign(registry[key], fields);
}

fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
console.log(`\nWrote ${Object.keys(updates).length} updated entries to ${REGISTRY_PATH}`);