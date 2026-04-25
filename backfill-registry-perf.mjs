#!/usr/bin/env node
// backfill-registry-perf.mjs
//
// Reads perf.json, calculates memory/performance statistics per model,
// and updates models-registry.json with measured data.
//
// Usage:
//   node backfill-registry-perf.mjs           # dry-run
//   node backfill-registry-perf.mjs --write   # apply changes

import fs from "fs";
import path from "path";
import os from "os";

const DRY_RUN = !process.argv.includes("--write");
const MIN_RUNS = 5; // Only backfill models with 5+ successful runs

const PERF_PATH = path.join(os.homedir(), ".claude/mem0/perf.json");
const REGISTRY_PATH = path.join(
  os.homedir(),
  "Projects/mem0-processor/config/models-registry.json"
);

// ─── HELPERS ─────────────────────────────────────────────────────────

function calculateStats(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  return {
    min: parseFloat(sorted[0].toFixed(2)),
    avg: parseFloat((values.reduce((a, b) => a + b) / values.length).toFixed(2)),
    max: parseFloat(sorted[sorted.length - 1].toFixed(2)),
  };
}

// ─── LOAD DATA ───────────────────────────────────────────────────────

console.log("Loading perf.json and models-registry.json...");

const perf = JSON.parse(fs.readFileSync(PERF_PATH, "utf8"));
const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));

// Build reverse map: perf model name → registry key
// This requires matching perf.json keys to registry keys
// Strategy: exact match, then fuzzy match on common patterns

const modelNameToKey = {};

for (const [regKey, entry] of Object.entries(registry)) {
  // Try exact match first
  modelNameToKey[regKey] = regKey;
  
  // Also map common variations
  // e.g., "rico03/qwen3.6-35b-a3b-opus" might appear as 
  // "rico03/qwen3.6-35b-a3b-opus" in perf.json
  const normalized = regKey.toLowerCase().replace(/[_\s-]+/g, '-');
  modelNameToKey[normalized] = regKey;
}

// ─── PROCESS MODELS ──────────────────────────────────────────────────

const updates = {};
let processedCount = 0;
let skippedCount = 0;

for (const [perfModelName, modelData] of Object.entries(perf)) {
  // Filter to successful runs with required fields
  const runs = modelData.runs.filter(r => 
    !r.failed && 
    r.peakGb != null && 
    r.noModelGb != null
  );
  
  if (runs.length < MIN_RUNS) {
    console.log(`  SKIP ${perfModelName}: only ${runs.length} successful runs (need ${MIN_RUNS}+)`);
    skippedCount++;
    continue;
  }
  
  // Find registry key
  let regKey = modelNameToKey[perfModelName];
  if (!regKey) {
    // Try normalized match
    const normalized = perfModelName.toLowerCase().replace(/[_\s-]+/g, '-');
    regKey = modelNameToKey[normalized];
  }
  
  if (!regKey || !registry[regKey]) {
    console.log(`  UNMATCHED ${perfModelName}: not found in registry`);
    skippedCount++;
    continue;
  }
  
  const entry = registry[regKey];
  
  // ─── CALCULATE MEMORY OVERHEAD ─────────────────────────────────────
  
  const overheads = runs.map(r => r.peakGb - r.noModelGb);
  const memStats = calculateStats(overheads);
  
  const memoryOverhead = {
    ...memStats,
    ratio: parseFloat((memStats.avg / entry.fileSizeGb).toFixed(2)),
    runs: runs.length,
  };
  
  // ─── CALCULATE PERFORMANCE METRICS ──────────────────────────────────
  
  const tpsVals = runs.map(r => r.tps).filter(x => x != null);
  const ttftVals = runs.map(r => r.ttft).filter(x => x != null);
  const prefillVals = runs
    .map(r => typeof r.prefillTps === 'string' ? parseFloat(r.prefillTps) : r.prefillTps)
    .filter(x => x != null && !isNaN(x));
  
  const tpsStats = calculateStats(tpsVals);
  const ttftStats = calculateStats(ttftVals);
  const avgPrefill = prefillVals.length
    ? parseFloat((prefillVals.reduce((a, b) => a + b) / prefillVals.length).toFixed(2))
    : null;
  
  const performance = {
    tps: tpsStats,
    ttft: ttftStats,
    prefillTps: avgPrefill,
    runs: runs.length,
  };
  
  // ─── CALCULATE SAFETY LIMITS ────────────────────────────────────────
  
  // Filter outliers: exclude runs >2 std deviations from mean
const mean = overheads.reduce((a,b) => a+b) / overheads.length;
const stdDev = Math.sqrt(overheads.map(x => (x - mean)**2).reduce((a,b) => a+b) / overheads.length);
const filtered = overheads.filter(x => Math.abs(x - mean) < 2 * stdDev);

const loadOverheads = runs.map(r => r.idleGb - r.noModelGb);
const loadStats = calculateStats(loadOverheads);
const peakStats = calculateStats(filtered); // use filtered data

// Gate checks
let minRamGb = (loadStats.avg * 1.05).toFixed(2);      // 5% margin to load
let recommendedRamGb = Math.ceil(peakStats.avg * 1.2);  // 20% margin to run
  
  // ─── BUILD UPDATE ───────────────────────────────────────────────────
  
  updates[regKey] = {
    memoryOverhead,
    performance,
    loadOverheads,
    minRamGb,
    recommendedRamGb,
  };
  
  processedCount++;
}

// ─── REPORT ──────────────────────────────────────────────────────────

if (Object.keys(updates).length === 0) {
  console.log(`\nNo models with ${MIN_RUNS}+ runs found.`);
  console.log(`Processed: ${processedCount}, Skipped: ${skippedCount}`);
  process.exit(0);
}

console.log(`\n${"=".repeat(70)}`);
console.log("UPDATES TO APPLY");
console.log("=".repeat(70));

for (const [key, data] of Object.entries(updates)) {
  console.log(`\n${key}:`);
  console.log(`  Memory overhead: ${data.memoryOverhead.avg}GB (${data.memoryOverhead.ratio}x), ` +
              `range ${data.memoryOverhead.min}-${data.memoryOverhead.max}GB`);
  console.log(`  Performance: ${data.performance.tps.avg} TPS avg, ` +
              `${data.performance.prefillTps} prefill TPS avg`);
  console.log(`  RAM requirements: ${data.minRamGb}GB min, ${data.recommendedRamGb}GB recommended`);
  console.log(`  Based on ${data.memoryOverhead.runs} runs`);
}

console.log(`\n${"=".repeat(70)}`);
console.log(`Total: ${processedCount} models processed, ${skippedCount} skipped`);
console.log(`Updates: ${Object.keys(updates).length} entries`);

if (DRY_RUN) {
  console.log(`\nDry run — pass --write to apply changes.`);
  process.exit(0);
}

// ─── APPLY UPDATES ───────────────────────────────────────────────────

for (const [key, data] of Object.entries(updates)) {
  Object.assign(registry[key], data);
}

fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
console.log(`\nWrote ${Object.keys(updates).length} updates to ${REGISTRY_PATH}`);
