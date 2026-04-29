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
// --upload            Upload summaries to mem0 (default: suppressed)
// --skip-summarized   Skip session/model pairs that already have a summary on disk

import { spawn } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { hasSummary } from "./lib/summary.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── ARGS ────────────────────────────────────────────────────────────────────

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i === -1) return null;
  const next = process.argv[i + 1];
  return (!next || next.startsWith("--")) ? true : next;
}

const SESSION          = arg("--session");
const MODELS           = arg("--models");
const TAG              = arg("--tag") || `sweep-${Date.now()}`;
const UPLOAD           = process.argv.includes("--upload");
const SAMPLER          = arg("--sampler");
const SKIP_SUMMARIZED  = process.argv.includes("--skip-summarized");

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

// ─── LOG ─────────────────────────────────────────────────────────────────────

const LOG_DIR  = path.join(os.homedir(), ".claude/mem0/logs");
const LOG_PATH = path.join(LOG_DIR, `sweep-${TAG}.log`);
fs.mkdirSync(LOG_DIR, { recursive: true });
const logStream = fs.createWriteStream(LOG_PATH, { flags: "a" });

function swLog(s) {
  logStream.write(s + "\n");
}

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
    const captured = [];
    const child = spawn("node", args, { stdio: ["inherit", "pipe", "pipe"] });

    function handle(chunk, dest) {
      dest.write(chunk);
      logStream.write(chunk);
      captured.push(chunk.toString());
    }

    child.stdout.on("data", chunk => handle(chunk, process.stdout));
    child.stderr.on("data", chunk => handle(chunk, process.stderr));

    child.on("close", (code) => {
      resolve({ sessionId, modelId, preset, runTag, code, elapsed: ((Date.now() - start) / 1000).toFixed(1), captured: captured.join("") });
    });

    child.on("error", (err) => {
      resolve({ sessionId, modelId, preset, runTag, code: -1, elapsed: ((Date.now() - start) / 1000).toFixed(1), err: err.message, captured: captured.join("") });
    });
  });
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

const totalRuns = sessionList.length * modelList.length * presetList.length;
const samplerLine = presetList[0] ? `  presets=${presetList.length} (${presetList.join(", ")})` : "";
const header = [
  `\nSweep: sessions=${sessionList.length}  models=${modelList.length}${samplerLine}  total=${totalRuns}  tag=${TAG}  upload=${UPLOAD}`,
  `Sessions: ${sessionList.join(", ")}`,
  `Models (${modelList.length}): ${modelList.join(", ")}`,
  `Log: ${LOG_PATH}\n`,
].join("\n");
console.log(header);
swLog(header);

const results = [];
let globalN = 0;

for (let si = 0; si < sessionList.length; si++) {
  const sessionId = sessionList[si];

  if (sessionList.length > 1) {
    const sessionHeader = `\n${"═".repeat(60)}\nSESSION ${si + 1}/${sessionList.length}: ${sessionId}\n${"═".repeat(60)}`;
    console.log(sessionHeader);
    swLog(sessionHeader);
  }

  for (let mi = 0; mi < modelList.length; mi++) {
    const modelId = modelList[mi];

    for (let pi = 0; pi < presetList.length; pi++) {
      const preset  = presetList[pi];
      const runTag  = preset
        ? `${TAG}-${si + 1}.${mi + 1}.${pi + 1}`
        : `${TAG}-${si + 1}.${mi + 1}`;
      globalN++;

      const presetLabel = preset ? `  sampler=${preset}` : "";
      const runHeader = `\n${"─".repeat(60)}\n[${globalN}/${totalRuns}] ${modelId}  session=${sessionId}${presetLabel}  tag=${runTag}\n${"─".repeat(60)}`;
      console.log(runHeader);
      swLog(runHeader);

      if (SKIP_SUMMARIZED && hasSummary(sessionId, modelId)) {
        console.log(`  → skip (already summarized)`);
        swLog(`  → skip (already summarized)`);
        results.push({ sessionId, modelId, preset, runTag, code: 0, elapsed: "0.0", skipped: true });
        continue;
      }

      const result = await runModel(sessionId, modelId, preset, runTag);
      results.push(result);

      const status = result.code === 0 ? "OK" : `FAIL (exit ${result.code})`;
      const resultLine = `\n→ ${status}  ${result.elapsed}s`;
      console.log(resultLine);
      swLog(resultLine);
    }
  }
}

// ─── SUMMARY ─────────────────────────────────────────────────────────────────

const summaryLines = [`\n${"═".repeat(60)}`, "SWEEP COMPLETE", "═".repeat(60)];

for (let si = 0; si < sessionList.length; si++) {
  const sessionId = sessionList[si];
  const sessionResults = results.filter(r => r.sessionId === sessionId);
  if (sessionList.length > 1) summaryLines.push(`\n  Session: ${sessionId}`);
  for (const r of sessionResults) {
    const status = r.skipped ? "-" : r.code === 0 ? "✓" : "✗";
    const presetCol = r.preset ? `  [${r.preset}]` : "";
    const note = r.skipped ? "  (skipped)" : r.err ? `  (${r.err})` : "";
    summaryLines.push(`  ${status} ${r.modelId.padEnd(45)}${presetCol.padEnd(16)} ${r.elapsed}s${note}`);
  }
}

const skipped = results.filter(r => r.skipped);
const ran     = results.filter(r => !r.skipped);
const failed  = ran.filter(r => r.code !== 0);
const skipNote = skipped.length > 0 ? `  ${skipped.length} skipped` : "";
summaryLines.push(`\n${ran.length - failed.length}/${ran.length} succeeded${skipNote}`);

const summaryBlock = summaryLines.join("\n");
console.log(summaryBlock);
swLog(summaryBlock);

if (failed.length > 0) {
  const replayHeader = `\n${"═".repeat(60)}\nFAILED RUN OUTPUT\n${"═".repeat(60)}`;
  console.log(replayHeader);
  swLog(replayHeader);
  for (const r of failed) {
    const runLabel = `\n--- ${r.modelId}  session=${r.sessionId}  exit=${r.code} ---`;
    console.log(runLabel);
    swLog(runLabel);
    const output = r.captured || r.err || "(no output captured)";
    process.stdout.write(output);
    logStream.write(output);
    if (!output.endsWith("\n")) { process.stdout.write("\n"); logStream.write("\n"); }
  }
  logStream.end();
  process.exit(1);
}

logStream.end();