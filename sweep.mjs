#!/usr/bin/env node
// sweep.mjs
//
// Reprocesses one session through multiple models sequentially, recording perf
// data for each without uploading to mem0.
//
// Usage:
//   node sweep.mjs --session <sessionId> --models <selectors> [--tag <name>] [--upload]
//
// --session   Session ID or slug to reprocess (passed as --reprocess to uploader)
// --models    Comma-separated selectors:
//               @<tag>        all models with that tag (e.g. @nvme, @qwen35, @small)
//               all           every model in the registry
//               nvme          shortcut for @nvme
//               wd-elements   shortcut for @wd-elements
//               <exact-key>   exact registry key
//               <substring>   matches one key (error if ambiguous)
//             Multiple selectors are unioned and deduplicated in order.
// --tag       Run tag prefix; each run gets <tag>-<n> (default: sweep-<timestamp>)
// --upload    Upload summaries to mem0 (default: suppressed)

import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── ARGS ────────────────────────────────────────────────────────────────────

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i === -1) return null;
  const next = process.argv[i + 1];
  return (!next || next.startsWith("--")) ? true : next;
}

const SESSION  = arg("--session");
const MODELS   = arg("--models");
const TAG      = arg("--tag") || `sweep-${Date.now()}`;
const UPLOAD   = process.argv.includes("--upload");

if (!SESSION || !MODELS) {
  console.error("Usage: node sweep.mjs --session <id> --models <a,b,...> [--tag <name>] [--upload]");
  process.exit(1);
}

const selectors = MODELS.split(",").map(m => m.trim()).filter(Boolean);
if (selectors.length === 0) {
  console.error("No models specified.");
  process.exit(1);
}

const REGISTRY_PATH = path.join(__dirname, "config/models-registry.json");
const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));

// ─── MODEL RESOLVER ───────────────────────────────────────────────────────────

function resolveModels(selectors, registry) {
  const resolved = [];
  const seen = new Set();

  for (const sel of selectors) {
    let matches = [];

    if (sel === "all") {
      matches = Object.keys(registry);
    } else if (sel === "nvme" || sel === "wd-elements") {
      matches = Object.keys(registry).filter(k => registry[k].source === sel);
    } else if (sel.startsWith("@")) {
      const tag = sel.slice(1);
      matches = Object.keys(registry).filter(k => registry[k].tags?.includes(tag));
      if (matches.length === 0) {
        console.error(`No models found with tag: ${tag}`);
        console.error("Available tags:", [...new Set(Object.values(registry).flatMap(e => e.tags ?? []))].sort().join(", "));
        process.exit(1);
      }
    } else if (registry[sel]) {
      matches = [sel];
    } else {
      matches = Object.keys(registry).filter(k => k.includes(sel));
      if (matches.length === 0) {
        console.error(`No model found matching: "${sel}"`);
        process.exit(1);
      }
      if (matches.length > 1) {
        console.error(`Ambiguous selector "${sel}" matches ${matches.length} models:`);
        matches.forEach(m => console.error(`  ${m}`));
        process.exit(1);
      }
    }

    for (const m of matches) {
      if (!seen.has(m)) {
        seen.add(m);
        resolved.push(m);
      }
    }
  }

  return resolved;
}

const modelList = resolveModels(selectors, registry);

const UPLOADER = path.join(__dirname, "claude-code-mem0-uploader.mjs");

// ─── RUN ─────────────────────────────────────────────────────────────────────

function runModel(modelId, runTag) {
  const args = [
    UPLOADER,
    "--llama", modelId,
    "--reprocess", SESSION,
    "--run-tag", runTag,
  ];
  if (!UPLOAD) args.push("--no-upload");

  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn("node", args, { stdio: "inherit" });

    child.on("close", (code) => {
      resolve({ modelId, runTag, code, elapsed: ((Date.now() - start) / 1000).toFixed(1) });
    });

    child.on("error", (err) => {
      resolve({ modelId, runTag, code: -1, elapsed: ((Date.now() - start) / 1000).toFixed(1), err: err.message });
    });
  });
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

console.log(`\nSweep: session=${SESSION}  tag=${TAG}  upload=${UPLOAD}`);
console.log(`Models (${modelList.length}): ${modelList.join(", ")}\n`);

const results = [];

for (let i = 0; i < modelList.length; i++) {
  const modelId = modelList[i];
  const runTag  = `${TAG}-${i + 1}`;

  console.log(`\n${"─".repeat(60)}`);
  console.log(`[${i + 1}/${modelList.length}] ${modelId}  tag=${runTag}`);
  console.log("─".repeat(60));

  const result = await runModel(modelId, runTag);
  results.push(result);

  const status = result.code === 0 ? "OK" : `FAIL (exit ${result.code})`;
  console.log(`\n→ ${status}  ${result.elapsed}s`);
}

// ─── SUMMARY ─────────────────────────────────────────────────────────────────

console.log(`\n${"═".repeat(60)}`);
console.log("SWEEP COMPLETE");
console.log("═".repeat(60));

for (const r of results) {
  const status = r.code === 0 ? "✓" : "✗";
  console.log(`  ${status} ${r.modelId.padEnd(45)} ${r.elapsed}s${r.err ? `  (${r.err})` : ""}`);
}

const failed = results.filter(r => r.code !== 0);
console.log(`\n${results.length - failed.length}/${results.length} succeeded`);
if (failed.length > 0) process.exit(1);