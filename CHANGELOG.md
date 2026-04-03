# Changelog — mem0-processor

---

## v7 — In Progress

### v7.0 — Steps 1–5 (committed d3631bb, 2026-04-02)
- `--reprocess <session-id>` flag
- `--no-upload` flag (skip mem0 write, for QA/benchmarking)
- RAM fix: ioreg AGXAccelerator "Alloc system memory" (GPU-wired RAM)
- Separate summarized vs uploaded state tracking
- Model perf store (`~/.claude/mem0_model_perf.json`): append-only per-session metrics
  (idleGb, preSessionIdleGb, peakGb, avgGb, tps, completionTokens, transcriptChars)
- Context cap logic: LM Studio max_context_length ceiling → RAM-constrained cap (112k chars
  for models with max peak > 12 GB) → fail-cap from smallest failed run's transcriptChars
- Fail-cap: `getModelFailCap()` derives hard ceiling from smallest failed perf store entry
- Sampler hoisted out of try block — catch can now log RAM + write failed perf entry
- Verbose skip logging: session ID + reason printed to console (was silent)
- Summary preview: first 1000 chars printed after each new summarization
- fetch wrapped in try/catch with char count in error messages
- `process.exit(0)` — hang mitigation (bandaid; root cause = unclosed HTTP handle, open)
- Removed unused `truncate` named import from fs
- Output directories: `~/.claude/mem0/state/`, `~/.claude/mem0/summaries/`, `~/.claude/mem0/logs/`

### v7.1 — Cleanup (tabled, not yet committed)
- Fold `--ignore-cache` into `--reprocess`: reprocessing should always bypass cache
- State file redesign: summary file presence = primary gate for "summarized"; state file =
  authoritative for upload status only; remove `summarized` as a logic gate; drop `?? true` default
- `log.write()` calls mirroring the two new verbose console skip messages
- Timestamp in summary header: prepend `[YYYY-MM-DD HH:MM]` to summary text before upload/cache
- `startedAt` / `endedAt` fields in state entry per session (enables elapsed time calc across
  related sessions)

---

## v8 — Benchmarking Infra (planned)

Goal: make clean benchmarking runs scriptable and the context cap data-driven.

- **Max safe context calc**: derive per-model chars-to-RAM curve from perf store
  (idle + preSessionIdle + peak vs transcriptChars). Replace static RAM-constrained cap
  with a model-specific computed ceiling.
- **Benchmarking run mode**: choose session IDs at runtime, scripted clean runs,
  more granular RAM logging (input processing vs output processing phases if feasible)
- **RAM warning tiers at model load**:
  - Tier 1: "This model is large — close non-essential processes"
  - Tier 2: "Run `sudo [vram command]` for more headroom" (when peak approaches system limit)
- **Model cooldown / KV flush**: monitor preSessionIdle vs idle; dynamic wait, or bail +
  prompt user to restart model if RAM doesn't settle
- **Interactive startup prompt** (maybe): session + flag selection via prompt instead of
  flag soup, once complexity warrants it

Difficulty: Medium (context calc, cooldown) → Medium-Hard (run mode, prompt UI)

---

## v9 — Programmatic Model Launch (planned)

Goal: launch models directly via mlx-lm instead of assuming LM Studio is running.
Enables clean isolated runs and more headroom control.

- Shell out to mlx-lm with model path, context, and param settings
- Model restart between benchmarking sessions
- turboquant integration investigation: shell out before mlx-lm launch, cache quantized
  output, load quantized model. Feasibility depends on CLI surface — needs investigation.
- Enables PARO model testing

Difficulty: Hard (mlx-lm launch), Unknown (turboquant)

---

## v10 — Refactor / Split / Cleanup (planned)

Final pass: split file, consolidate logic, remove dead flags, clean up session decision flow.
Separate the "what to do with this session" logic (currently checked in multiple places).

---

## Backlog / Post-v10

- Quality scoring formalization (1–5 per session)
- infer=false or replace mem0 with local markdown files
- Chunking: compaction-anchor approach (detect Claude compaction summaries, use as anchor;
  process summary + everything after it)
- Session grouping / summary crosslinking: merge or cross-reference summaries for related
  sessions (date proximity + topic overlap); design depends on infer=false outcome
