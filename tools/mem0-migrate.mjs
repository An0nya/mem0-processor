// mem0-migrate-v3.mjs
// Discovers ALL memories across every scope (user, agent, run),
// re-posts each under user_id=anya with no run_id/agent_id,
// preserving session info in metadata instead.
// Deletes originals after successful migration.

import fs from "fs";
import path from "path";
import os from "os";

const MEM0_API_KEY = process.env.MEM0_API_KEY;
const SOURCE_USER_ID = "anya";
const TARGET_USER_ID = "anya-sessions";
const UNKNOWN_DUMP = path.join(os.homedir(), ".claude", "mem0_migrate_unknown.json");
const MIGRATED_LOG = path.join(os.homedir(), ".claude", "mem0_migrate_log.json");
const DRY_RUN = process.argv.includes("--dry-run");
const SKIP_DELETE = process.argv.includes("--skip-delete");

if (!MEM0_API_KEY) {
  console.error("MEM0_API_KEY not set");
  process.exit(1);
}

const headers = {
  "Content-Type": "application/json",
  Authorization: `Token ${MEM0_API_KEY}`,
};

// ─── V2 PAGINATED FETCH ────────────────────────────────────────
// Uses POST /v2/memories/ with body filters + pagination.
// Returns all pages concatenated.
async function fetchAllV2(filters, label) {
  const memories = [];
  let page = 1;
  const pageSize = 100;

  while (true) {
    const url = `https://api.mem0.ai/v2/memories/?page=${page}&page_size=${pageSize}`;
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ filters }),
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`POST /v2/memories/ (${label}) failed ${res.status}: ${body.slice(0, 300)}`);
    }

    const data = await res.json();
    const batch = data.results ?? [];
    memories.push(...batch);

    if (!data.next) break;
    page++;
  }

  if (memories.length > 0) {
    console.log(`  ${label}: ${memories.length} memories`);
  }
  return memories;
}

// ─── ENTITY ENUMERATION ────────────────────────────────────────
async function listEntities() {
  const res = await fetch("https://api.mem0.ai/v1/entities/", { headers });
  if (!res.ok) throw new Error(`GET /v1/entities/ failed ${res.status}`);
  return res.json();
}

// ─── DISCOVER ALL MEMORIES ─────────────────────────────────────
async function discoverAllMemories() {
  const entities = await listEntities();
  const seen = new Map(); // id → memory object

  // 1. Fetch user-scoped memories (the 198 you already see)
  const userMemories = await fetchAllV2(
    { AND: [{ user_id: SOURCE_USER_ID }] },
    `user_id=${SOURCE_USER_ID}`
  );
  for (const m of userMemories) seen.set(m.id, m);

  // 2. Fetch each run's memories (the hidden 222)
  //    CRITICAL: user_id must be in the filter even for run-scoped queries.
  //    The MCP auto-injects it, but the raw API scopes by Mem0-User-ID header
  //    (an API key hash, not "anya"), so bare run_id filters match nothing.
  const runs = entities.results?.filter((e) => e.type === "run") ?? [];
  if (runs.length > 0) {
    console.log(`  Found ${runs.length} run entities, checking each...`);
    for (const run of runs) {
      const runMemories = await fetchAllV2(
        { AND: [{ user_id: SOURCE_USER_ID }, { run_id: run.name }] },
        `run_id=${run.name.slice(0, 8)}…`
      );
      for (const m of runMemories) {
        if (!seen.has(m.id)) {
          // Tag where we found it so migration can track provenance
          m._sourceScope = { run_id: run.name };
          seen.set(m.id, m);
        }
      }
    }
  }

  // 3. Fetch agent-scoped memories (probably 0, but be thorough)
  const agents = entities.results?.filter((e) => e.type === "agent") ?? [];
  for (const agent of agents) {
    const agentMemories = await fetchAllV2(
      { AND: [{ user_id: SOURCE_USER_ID }, { agent_id: agent.name }] },
      `agent_id=${agent.name}`
    );
    for (const m of agentMemories) {
      if (!seen.has(m.id)) {
        m._sourceScope = { agent_id: agent.name };
        seen.set(m.id, m);
      }
    }
  }

  return [...seen.values()];
}

// ─── RE-POST MEMORY ────────────────────────────────────────────
// Stores under user_id=anya only. No run_id or agent_id scoping.
// Session/model info goes into metadata where it's queryable but
// doesn't create invisible namespaces.
async function repostMemory(memory) {
  const originalMeta = memory.metadata ?? {};

  const newMetadata = {
    ...originalMeta,
    migrated: true,
    migratedAt: new Date().toISOString(),
    originalId: memory.id,
  };

  // Preserve session provenance if it came from a run scope
  if (memory.session_id) newMetadata.sessionId = memory.session_id;
  if (memory._sourceScope?.run_id) newMetadata.originalRunId = memory._sourceScope.run_id;
  if (memory._sourceScope?.agent_id) newMetadata.originalAgentId = memory._sourceScope.agent_id;

  const body = {
    messages: [{ role: "user", content: memory.memory }],
    user_id: TARGET_USER_ID,
    // No agent_id, no run_id — flat namespace
    infer: false, // Store verbatim; these are already-processed facts
    metadata: newMetadata,
  };

  const res = await fetch("https://api.mem0.ai/v1/memories/", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST failed ${res.status}: ${text.slice(0, 300)}`);
  }

  return res.json();
}

// ─── DELETE ORIGINAL ───────────────────────────────────────────
async function deleteMemory(id) {
  const res = await fetch(`https://api.mem0.ai/v1/memories/${id}/`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`DELETE ${id} failed ${res.status}: ${text.slice(0, 200)}`);
  }
}

// ─── MAIN ──────────────────────────────────────────────────────
async function main() {
  if (DRY_RUN) console.log("🔍 DRY RUN — no writes or deletes\n");
  if (SKIP_DELETE) console.log("⚠ SKIP-DELETE — originals will NOT be removed\n");

  console.log("Discovering memories across all scopes...");
  const allMemories = await discoverAllMemories();
  console.log(`\nTotal unique memories: ${allMemories.length}\n`);

  if (allMemories.length === 0) {
    console.log("Nothing to migrate.");
    return;
  }

  // Separate: memories already in user-only scope (no run/agent)
  // vs memories trapped in run/agent scopes that need migration
  const needsMigration = allMemories.filter((m) => m._sourceScope);
  const alreadyFlat = allMemories.filter((m) => !m._sourceScope);

  console.log(`Already in user scope (no action needed): ${alreadyFlat.length}`);
  console.log(`Trapped in run/agent scopes (need migration): ${needsMigration.length}\n`);

  const migrationLog = [];
  let migrated = 0;
  let failed = 0;

  for (const memory of needsMigration) {
    const scope = memory._sourceScope;
    const scopeLabel = scope.run_id
      ? `run:${scope.run_id.slice(0, 8)}…`
      : `agent:${scope.agent_id}`;

    console.log(`  → ${memory.id.slice(0, 8)}… [${scopeLabel}] "${memory.memory.slice(0, 60)}…"`);

    if (DRY_RUN) {
      console.log(`    [DRY-RUN] Would re-post to user_id=${TARGET_USER_ID}, then delete original`);
      migrated++;
      continue;
    }

    try {
      const result = await repostMemory(memory);
      migrationLog.push({
        originalId: memory.id,
        sourceScope: scope,
        newResult: result,
        text: memory.memory.slice(0, 100),
      });

      if (!SKIP_DELETE) {
        await deleteMemory(memory.id);
        console.log(`    ✓ Migrated + deleted original`);
      } else {
        console.log(`    ✓ Migrated (original kept)`);
      }
      migrated++;
    } catch (err) {
      failed++;
      console.error(`    ✗ Failed: ${err.message}`);
    }
  }

  // Write migration log
  if (migrationLog.length > 0) {
    fs.writeFileSync(MIGRATED_LOG, JSON.stringify(migrationLog, null, 2));
    console.log(`\nMigration log written to: ${MIGRATED_LOG}`);
  }

  console.log(`\nDone. Migrated: ${migrated} | Failed: ${failed} | Already flat: ${alreadyFlat.length}`);
}

main();
