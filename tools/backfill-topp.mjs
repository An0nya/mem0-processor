#!/usr/bin/env node
// backfill-topp.mjs
// Backfills topP: 0.9 onto runs that have sampler fields (minP/temp/topK)
// but no topP — these were run under llama-server's implicit top-p 0.9 default.
// Runs with all-null sampler fields (pre-instrumentation) are left untouched.
//
// Usage: node backfill-topp.mjs [path/to/perf.json]
// Backs up the original file to perf.json.bak before writing.

import fs from "fs";
import path from "path";

const PERF_PATH = process.argv[2] ?? "./perf.json";

if (!fs.existsSync(PERF_PATH)) {
  console.error(`File not found: ${PERF_PATH}`);
  process.exit(1);
}

// ── Dry-run check: report topP states across instrumented runs ────────────────
const raw = fs.readFileSync(PERF_PATH, "utf8");
const data = JSON.parse(raw);

const states = new Set();
for (const model of Object.values(data)) {
  for (const run of model.runs) {
    if (run.minP !== null && run.minP !== undefined) {
      states.add(typeof run.topP === "undefined" ? "undefined" : JSON.stringify(run.topP));
    }
  }
}
console.log("topP states across instrumented runs:", [...states]);

// ── Backup ────────────────────────────────────────────────────────────────────
const backupPath = PERF_PATH + ".bak";
fs.copyFileSync(PERF_PATH, backupPath);
console.log(`Backup written to: ${backupPath}`);

// ── Backfill ──────────────────────────────────────────────────────────────────
let patched = 0;
let skippedPreInstrumentation = 0;
let skippedAlreadySet = 0;

for (const model of Object.values(data)) {
  for (const run of model.runs) {
    const hassampler = run.minP !== null && run.minP !== undefined;

    if (!hassampler) {
      skippedPreInstrumentation++;
      continue;
    }

    if (typeof run.topP !== "undefined") {
      skippedAlreadySet++;
      continue;
    }

    run.topP = 0.9;
    patched++;
  }
}

fs.writeFileSync(PERF_PATH, JSON.stringify(data, null, 2) + "\n");

console.log(`Patched:                   ${patched}`);
console.log(`Skipped (pre-instrument):  ${skippedPreInstrumentation}`);
console.log(`Skipped (topP already set): ${skippedAlreadySet}`);
