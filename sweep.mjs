#!/usr/bin/env node
// sweep.mjs
//
// Reprocesses one or more sessions through multiple models sequentially,
// recording perf data for each without uploading to mem0.
//
// Usage:
//   node sweep.mjs --session <id>[,<id>,...] --models <selectors> [--sampler <presets>] [--tag <name>] [--upload]
//
// --session   One or more session IDs/slugs, comma-separated.
//             Each is passed as --reprocess to the uploader.
//             Run order: sessions × models × presets (outer→inner).
// --models    Comma-separated selectors:
//               @<tag>        all models with that tag (e.g. @nvme, @qwen35, @small)
//               @t1+@t2       AND: models that have ALL listed tags
//               all           every model in the registry
//               nvme          shortcut for @nvme
//               wd-elements   shortcut for @wd-elements
//               <exact-key>   exact registry key
//               <substring>   matches one key (error if ambiguous)
//             Multiple selectors are unioned and deduplicated in order.
// --sampler   Comma-separated preset names from config/sampler-presets.json.
//             Omit to run each model once with its registry sampler defaults.
// --tag       Run tag prefix; each run gets <tag>-<si>.<mi>[.<pi>] (default: sweep-<timestamp>)
//             si = session index, mi = model index, pi = preset index (omitted when no --sampler).
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
const SAMPLER  = arg("--sampler");

if (!SESSION || !MODELS) {
  console.error("Usage: node sweep.mjs --session <id>[,<id>,...] --models <a,b,...> [--sampler <presets>] [--tag <name>] [--upload]");
  process.exit(1);
}

const sessionList = SESSION.split(",").map(s => s.trim()).filter(Boolean);
if (sessionList.length === 0) {
  console.error("No sessions specified.");
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
    } else if (sel.includes("+")) {
      const parts = sel.split("+").map(s => s.trim());
      const tagSets = parts.map(part => {
        if (!part.startsWith("@")) {
          console.error(`AND syntax requires @tag terms, got: "${part}"`);
          process.exit(1);
        }
        return part.slice(1);
      });
      matches = Object.keys(registry).filter(k =>
        tagSets.every(tag => registry[k].tags?.includes(tag))
      );
      if (matches.length === 0) {
        console.error(`No models found matching all tags: ${tagSets.join(", ")}`);
        console.error("Available tags:", [...new Set(Object.values(registry).flatMap(e => e.tags ?? []))].sort().join(", "));
        process.exit(1);
      }
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

const PRESETS_PATH = path.join(__dirname, "config/sampler-presets.json");
const presetsRegistry = JSON.parse(fs.readFileSync(PRESETS_PATH, "utf8"));

const presetList = (() => {
  if (!SAMPLER) return [null]; // null = no override, use registry defaults
  const names = SAMPLER.split(",").map(s => s.trim()).filter(Boolean);
  for (const name of names) {
    if (!presetsRegistry[name]) {
      console.error(`Unknown sampler preset "${name}". Available: ${Object.keys(presetsRegistry).join(", ")}`);
      process.exit(1);
    }
  }
  return names;
})();

const UPLOADER = path.join(__dirname, "claude-code-mem0-uploader.mjs");

// ─── RUN ─────────────────────────────────────────────────────────────────────

function runModel(sessionId, modelId, preset, runTag) {
  const args = [
    UPLOADER,
    "--llama", modelId,
    "--reprocess", sessionId,
    "--run-tag", runTag,
  ];
  if (preset) args.push("--sampler", preset);
  if (!UPLOAD) args.push("--no-upload");

  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn("node", args, { stdio: "inherit" });

    child.on("close", (code) => {
      resolve({ sessionId, modelId, preset, runTag, code, elapsed: ((Date.now() - start) / 1000).toFixed(1) });
    });

    child.on("error", (err) => {
      resolve({ sessionId, modelId, preset, runTag, code: -1, elapsed: ((Date.now() - start) / 1000).toFixed(1), err: err.message });
    });
  });
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

const totalRuns = sessionList.length * modelList.length * presetList.length;
const samplerLine = presetList[0] ? `  presets=${presetList.length} (${presetList.join(", ")})` : "";
console.log(`\nSweep: sessions=${sessionList.length}  models=${modelList.length}${samplerLine}  total=${totalRuns}  tag=${TAG}  upload=${UPLOAD}`);
console.log(`Sessions: ${sessionList.join(", ")}`);
console.log(`Models (${modelList.length}): ${modelList.join(", ")}\n`);

const results = [];
let globalN = 0;

for (let si = 0; si < sessionList.length; si++) {
  const sessionId = sessionList[si];

  if (sessionList.length > 1) {
    console.log(`\n${"═".repeat(60)}`);
    console.log(`SESSION ${si + 1}/${sessionList.length}: ${sessionId}`);
    console.log("═".repeat(60));
  }

  for (let mi = 0; mi < modelList.length; mi++) {
    const modelId = modelList[mi];

    for (let pi = 0; pi < presetList.length; pi++) {
      const preset  = presetList[pi];
      const runTag  = preset
        ? `${TAG}-${si + 1}.${mi + 1}.${pi + 1}`
        : `${TAG}-${si + 1}.${mi + 1}`;
      globalN++;

      console.log(`\n${"─".repeat(60)}`);
      const presetLabel = preset ? `  sampler=${preset}` : "";
      console.log(`[${globalN}/${totalRuns}] ${modelId}  session=${sessionId}${presetLabel}  tag=${runTag}`);
      console.log("─".repeat(60));

      const result = await runModel(sessionId, modelId, preset, runTag);
      results.push(result);

      const status = result.code === 0 ? "OK" : `FAIL (exit ${result.code})`;
      console.log(`\n→ ${status}  ${result.elapsed}s`);
    }
  }
}

// ─── SUMMARY ─────────────────────────────────────────────────────────────────

console.log(`\n${"═".repeat(60)}`);
console.log("SWEEP COMPLETE");
console.log("═".repeat(60));

for (let si = 0; si < sessionList.length; si++) {
  const sessionId = sessionList[si];
  const sessionResults = results.filter(r => r.sessionId === sessionId);
  if (sessionList.length > 1) console.log(`\n  Session: ${sessionId}`);
  for (const r of sessionResults) {
    const status = r.code === 0 ? "✓" : "✗";
    const presetCol = r.preset ? `  [${r.preset}]` : "";
    console.log(`  ${status} ${r.modelId.padEnd(45)}${presetCol.padEnd(16)} ${r.elapsed}s${r.err ? `  (${r.err})` : ""}`);
  }
}

const failed = results.filter(r => r.code !== 0);
console.log(`\n${results.length - failed.length}/${results.length} succeeded`);
if (failed.length > 0) process.exit(1);