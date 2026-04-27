#!/usr/bin/env node
// backfill-registry-tags.mjs
//
// Derives and syncs `tags[]` on each registry entry from existing fields.
// Managed tags (defined below) are fully replaced on each run — stale ones
// are removed and correct ones are added. Manual tags are never touched.
//
// Usage:
//   node backfill-registry-tags.mjs           # dry-run
//   node backfill-registry-tags.mjs --write   # applies changes

import fs from "fs";
import path from "path";
import os from "os";

const DRY_RUN = !process.argv.includes("--write");
const REGISTRY_PATH = path.join(
  os.homedir(),
  "Projects/mem0-processor/config/models-registry.json"
);

// ─── HELPERS ─────────────────────────────────────────────────────────────────

function parseParamsToB(str) {
  const m = str.match(/([\d.]+)\s*(B|M|K)/i);
  if (!m) return null;
  const val = parseFloat(m[1]);
  const unit = m[2].toUpperCase();
  if (unit === "B") return val;
  if (unit === "M") return val / 1000;
  if (unit === "K") return val / 1_000_000;
  return null;
}

function normalizeQuantType(qt) {
  if (!qt) return null;
  // IQ types: "IQ4_XS - 4.25 bpw" → "iq4_xs"
  if (/^IQ/i.test(qt)) return qt.split(/\s/)[0].toLowerCase();
  // Q types with size suffix: "Q4_K - Medium" → "q4_k_m"
  const qMatch = qt.match(/^(Q[\w_]+)\s*-\s*(Medium|Large|Small|XL|XXL|XS|XXS)/i);
  if (qMatch) return `${qMatch[1].toLowerCase()}_${qMatch[2][0].toLowerCase()}`;
  // Simple Q types: "Q8_0"
  if (/^Q\d/i.test(qt)) return qt.split(/\s/)[0].toLowerCase();
  if (/^BF16$/i.test(qt)) return "bf16";
  if (/^F16$/i.test(qt))  return "f16";
  if (/^MXFP4/i.test(qt)) return "mxfp4";
  return null;
}

// Tags this script fully owns — stale values are removed, correct ones added.
// Anything not in this set is treated as a manual tag and left alone.
const MANAGED_TAGS = new Set([
  "bare",
  "dense", "moe",
  "nvme", "wd-elements",
  "tiny", "small", "medium", "large", "xlarge",
  "apex", "imatrix", "ud", "unsloth",
  "bf16", "f16", "mxfp4",
  // IQ and Q quant families — matched by prefix below
]);

function isManagedTag(tag) {
  if (MANAGED_TAGS.has(tag)) return true;
  if (/^iq\d/i.test(tag)) return true;
  if (/^q\d/i.test(tag))  return true;
  return false;
}

// ─── TAG DERIVATION ──────────────────────────────────────────────────────────

function deriveTags(key, entry) {
  const tags = new Set();

  // bare: no arch and no modelParams means metadata hasn't been backfilled yet
  const hasMetadata = entry.arch || entry.modelParams;
  if (!hasMetadata) tags.add("bare");

  // arch: dense / moe
  if (entry.arch === "dense") tags.add("dense");
  if (entry.arch === "moe")   tags.add("moe");

  // source: nvme / wd-elements
  if (entry.source) tags.add(entry.source);

  // size bucket by parameter count
  if (entry.modelParams) {
    const b = parseParamsToB(entry.modelParams);
    if (b !== null) {
      if      (b < 5)  tags.add("tiny");
      else if (b < 15) tags.add("small");
      else if (b < 30) tags.add("medium");
      else if (b < 50) tags.add("large");
      else             tags.add("xlarge");
    }
  }

  // quant method
  const qt = normalizeQuantType(entry.quantType);
  if (qt) tags.add(qt);

  // quant provenance from key name
  const lkey = key.toLowerCase();
  if (lkey.includes("-ud-") || lkey.includes("/ud-")) {
    tags.add("ud");
  } else if (lkey.includes("unsloth")) {
    tags.add("unsloth");
  }
  if (lkey.includes("apex")) tags.add("apex");
  if (entry.hasImatrix)      tags.add("imatrix");

  // architecture / model family
  if (entry.architecture) tags.add(entry.architecture);

  return [...tags].sort();
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────

const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));
const updates = {};

for (const [key, entry] of Object.entries(registry)) {
  const derived = new Set(deriveTags(key, entry));
  const existing = entry.tags ?? [];

  const toAdd    = [...derived].filter(t => !existing.includes(t));
  const toRemove = existing.filter(t => isManagedTag(t) && !derived.has(t));

  if (toAdd.length > 0 || toRemove.length > 0) {
    updates[key] = { toAdd, toRemove };
  }
}

if (Object.keys(updates).length === 0) {
  console.log("No tag changes — registry is up to date.");
  process.exit(0);
}

for (const [key, { toAdd, toRemove }] of Object.entries(updates)) {
  console.log(`  ${key}`);
  if (toAdd.length)    console.log(`    + ${toAdd.join(", ")}`);
  if (toRemove.length) console.log(`    - ${toRemove.join(", ")}`);
}

if (DRY_RUN) {
  console.log(`\nDry run — ${Object.keys(updates).length} entries would be updated. Pass --write to apply.`);
  process.exit(0);
}

for (const [key, { toAdd, toRemove }] of Object.entries(updates)) {
  const existing = registry[key].tags ?? [];
  const removeSet = new Set(toRemove);
  registry[key].tags = [...existing.filter(t => !removeSet.has(t)), ...toAdd].sort();
}

fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
console.log(`\nWrote ${Object.keys(updates).length} updated entries to ${REGISTRY_PATH}`);