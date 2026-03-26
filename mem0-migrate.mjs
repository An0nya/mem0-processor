// mem0-migrate.mjs
// Fetches claude-code-sessions memories from two scopes (agent-only + user-only),
// re-posts each to the correct model-scoped user_id,
// deletes the original, and dumps unrecognized entries to a temp file.

import fs from "fs";
import path from "path";
import os from "os";

const MEM0_API_KEY = process.env.MEM0_API_KEY;
const AGENT_ID = "claude-code-sessions";
const SOURCE_USER_ID = "anya";
const UNKNOWN_DUMP = path.join(os.homedir(), ".claude", "mem0_migrate_unknown.json");
const DRY_RUN = process.argv.includes("--dry-run");

if (!MEM0_API_KEY) {
  console.error("MEM0_API_KEY not set");
  process.exit(1);
}

const headers = {
  "Content-Type": "application/json",
  "Authorization": `Token ${MEM0_API_KEY}`,
};

// Mirror the same slug logic as the uploader
function modelToUserId(model) {
  const slug = model.replace(/[^a-zA-Z0-9-]/g, "-").replace(/-+/g, "-").toLowerCase();
  return `anya-${slug}`;
}

// ─── FETCH ALL MEMORIES ──────────────────────────────────────────
async function fetchScope(params, label) {
  const memories = [];
  let page = 1;
  const pageSize = 100;

  while (true) {
    const qs = new URLSearchParams({ ...params/*, page, page_size: pageSize*/ }).toString();
    const url = `https://api.mem0.ai/v1/memories/?${qs}`;
    const res = await fetch(url, { headers });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`GET memories (${label}) failed ${res.status}: ${body.slice(0, 200)}`);
    }

    const data = await res.json();
    const batch = Array.isArray(data) ? data : (data.results ?? []);
    memories.push(...batch);

    if (!data.next) break;  // null = no more pages
    page++;
  }

  console.log(`  ${label}: ${memories.length} found`);
  return memories;
}

async function fetchAllMemories() {
  // Fetch both scopes separately — mem0 treats filters as AND, not OR
  const [agentOnly, userOnly] = await Promise.all([
    fetchScope({ agent_id: AGENT_ID }, `agent_id=${AGENT_ID} only`),
    fetchScope({ user_id: SOURCE_USER_ID }, `user_id=${SOURCE_USER_ID} only`),
  ]);

  // Deduplicate by id in case any entries appear in both
  const seen = new Set();
  const all = [];
  for (const m of [...agentOnly, ...userOnly]) {
    if (!seen.has(m.id)) {
      seen.add(m.id);
      all.push(m);
    }
  }
  return all;
}

// ─── RE-POST MEMORY ──────────────────────────────────────────────
async function repostMemory(memory, targetUserId) {
  const body = {
    messages: [{ role: "user", content: memory.memory }],
    agent_id: AGENT_ID,
    user_id: targetUserId,
    run_id: memory.run_id ?? undefined,
    infer: true,
    metadata: {
      ...(memory.metadata ?? {}),
      migratedFrom: SOURCE_USER_ID,
      originalId: memory.id,
    },
  };

  const res = await fetch("https://api.mem0.ai/v1/memories/", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST failed ${res.status}: ${text.slice(0, 200)}`);
  }

  return res.json();
}

// ─── DELETE ORIGINAL ─────────────────────────────────────────────
async function deleteMemory(id) {
  const res = await fetch(`https://api.mem0.ai/v1/memories/${id}/`, {
    method: "DELETE",
    headers,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`DELETE failed ${res.status}: ${text.slice(0, 200)}`);
  }
}

// ─── MAIN ────────────────────────────────────────────────────────
async function main() {
  if (DRY_RUN) console.log("🔍 DRY RUN — no writes or deletes will occur\n");

  console.log(`Fetching memories across two scopes...`);
  const memories = await fetchAllMemories();
  console.log(`Total unique memories: ${memories.length}\n`);

  if (memories.length === 0) {
    console.log("Nothing to migrate.");
    return;
  }

  const unknown = [];
  let migrated = 0;
  let failed = 0;

  for (const memory of memories) {
    const model = memory.metadata?.summarizedBy;

    if (!model) {
      //console.warn(`  ⚠ No summarizedBy on memory ${memory.id} — queuing for manual review`);
      unknown.push(memory);
      continue;
    }

    const targetUserId = modelToUserId(model);
    console.log(`  → ${memory.id} :: ${model} → ${targetUserId}`);

    if (DRY_RUN) {
      console.log(`    [DRY-RUN] Would re-post then delete original`);
      migrated++;
      continue;
    }

    try {
      await repostMemory(memory, targetUserId);
      await deleteMemory(memory.id);
      migrated++;
      console.log(`    ✓ Migrated`);
    } catch (err) {
      failed++;
      console.error(`    ✗ Failed: ${err.message}`);
    }
  }

  // Dump unknowns to file
  if (unknown.length > 0) {
    fs.writeFileSync(UNKNOWN_DUMP, JSON.stringify(unknown, null, 2));
    console.log(`\n⚠ ${unknown.length} memory/memories with no summarizedBy written to:\n  ${UNKNOWN_DUMP}`);
  }

  console.log(`\nDone. Migrated: ${migrated} | Failed: ${failed} | Unknown: ${unknown.length}`);
}

main();
