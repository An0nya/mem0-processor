# Changelog — mem0-processor

Script version is primary. Prompt revisions are sub-items within the script
version that ships them ("prompt iteration N"), not a parallel version track.

Historical: v1–6 were pre-git iterations of the script + prompt together. v7
formalized the split when benchmarking requirements piled up.

---

## v7 — Stable baseline

### v7.0 — Steps 1–5 (committed d3631bb, 2026-04-02)

- `--reprocess <session-id>` flag
- `--no-upload` flag (skip mem0 write, for QA/benchmarking)
- RAM fix: ioreg `AGXAccelerator` "Alloc system memory" (GPU-wired RAM, invisible to `ps rss`)
- Separate summarized vs uploaded state tracking
- Model perf store at `~/.claude/mem0_model_perf.json`: append-only per-session entries
  (`idleGb`, `preSessionIdleGb`, `peakGb`, `avgGb`, `tps`, `completionTokens`, `transcriptChars`)
- Context cap: `max_context_length` from LM Studio v0 API as hard ceiling, RAM-constrained
  fallback (112k chars for models with max peak > 12 GB), fail-cap derived from smallest
  failed `transcriptChars` via `getModelFailCap()`
- Sampler hoisted out of `try` block so `catch` can log RAM + write failed perf entry
- Verbose skip logging: session ID + reason to console
- Summary preview: first 1000 chars printed after each new summarization
- Fetch wrapped in try/catch with char count in error messages
- `process.exit(0)` — hang mitigation bandaid (root cause = unclosed HTTP keep-alive, open)
- Removed unused `truncate` named import from `fs`
- Output directories: `~/.claude/mem0/state/`, `~/.claude/mem0/summaries/`, `~/.claude/mem0/logs/`

### v7.1 — Cleanup (committed 22683f2 + 9b6c224, 2026-04-02)

- Fold `--ignore-cache` into `--reprocess`; `--ignore-cache` flag removed
- State file redesign: summary file presence = primary gate for "summarized"; state file
  is authoritative for upload status only; `summarized` dropped as a logic gate; `?? true`
  default removed
- `log.write()` calls mirroring the verbose console skip messages
- Timestamp in summary header: `[YYYY-MM-DD HH:MM → HH:MM]` from session JSONL (not
  processing time) prepended to summary before upload/cache
- `startedAt` / `endedAt` fields in state entry per session
- Summary archiving: on `--reprocess`, existing cached summary is moved to
  `~/.claude/mem0/summaries/archive/<slug>/<sessionId>--<timestamp>.txt` before overwrite

---

## v7.2 — Telemetry expansion + context cap simplification + prompt iteration 3

**Status: shipped.**

Grouped by theme because the changes were made together and depend on each other.

### Telemetry expansion

- Sampler now returns swap + memory pressure alongside GPU RAM:
  - Swap via `sysctl vm.swapusage` (GB, with unit parsing for K/M/G)
  - Memory pressure via `memory_pressure` CLI, computed as `100 - free%` so higher = worse
  - New fields: `startingSwap`, `maxSwap`, `peakPressure`, `pressureAvg`
- `preSessionIdleGb` sampled per-session, distinct from run-start `idleGb`
- Run-start idle sampling extended to RAM + swap + pressure (was RAM only), logged once
  before the inference loop begins
- `summarizeSession` return expanded: `ttft`, `genTime`, `promptTokens`, `reasoningTokens`
- `prefillTps` calculated as `promptTokens / ttft`, logged per session
- `printSummary` expanded with prefill tok/s avg/peak/min, swap peak/avg, pressure peak/avg
- Perf store entries gain `loadedContext`, `startingSwap`, `maxSwap`, `peakPressure`,
  `pressureAvg`, `ttft`, `genTime`, `promptTokens`, `reasoningTokens`

### Response handling

- Dual reasoning + content handling in LM Studio v0 response parse. Three cases:
  - Content only → use as-is
  - Content + reasoning → summary is content, reasoning trace appended as HTML comment
    for optional inspection (explicitly marked as intentional inclusion)
  - Reasoning only (content block empty because reasoning ate the token budget) →
    fallback to reasoning as the summary with `<!-- reasoning-only fallback -->` marker
- `max_tokens` bumped to 8182 (lmstudio) / 2048 (anthropic) to avoid truncation on
  reasoning models

### Context cap simplification

- All fail-cap and RAM-constrained logic removed. Reasoning (documented in-code):
  ~95% of observed failures were fetch timeouts, not OOM; timeout was extended via undici
  `Agent` (30 min headers/body), so failed runs are no longer a useful signal for sizing.
- New ceiling: `CONTEXT_CAP = 64_000 * 3.5` tokens-to-chars, intersected with
  `modelInfo.loaded_context_length * 3.5`. Hard cap; oversize transcripts skip.
- `--no-token-cap` flag added as the intended override (see blockers).
- `getModelFailCap()` and the commented `maxPeak`/`failCap`/`ramConstrained` block left
  in-file pending v8 cleanup. Marked as dead code.

### Summarization prompt — iteration 3

- Restructured around trust calibration and session texture (supersedes the earlier
  sectioned narrative format). New sections:
  - **Goal** — real objective, 1–3 sentences
  - **What Happened & Why** — narrative, not a log
  - **Competence Signals** — what the user independently identified/caught/knew, plus
    deference gaps
  - **Mistakes & What Caused Them** — error, attribution, whether caught, root assumption
  - **Decisions (attributed)** — `[USER]` / `[CLAUDE]` / `[USER-APPROVED]`, flagging
    confident framing that masked wrong assumptions
  - **Open Threads** — unfinished work, concrete
- Default attribution is `[CLAUDE]` when uncertain. Sub-agent calls counted as Claude's work.

### Misc

- `infer: false` as the default (was env-gated). Inference layer was producing
  hallucinated memories from adjacent context; raw summary blobs are the canonical store.
- `CONFIG.mem0.userId = "summary-sessions"` — benchmarking isolation from the main
  `anya` entity
- Auto-register any perf-store model into `MODELS` at startup (runtime only; perf store
  is the durable registry)

### Fixes (shipped with v7.2)

- `--no-token-cap` wired: bypasses script CONTEXT_CAP ceiling only; model's loaded
  context window remains the hard limit.
- Header docstring updated: correct `user_id`, `infer` default, context cap behavior,
  perf field list.
- `getModelFailCap()` and `getModelMaxPeak()` removed; commented cap block cleared;
  v8 TODO left in place.
- `loadedContext` perf field renamed to `loadedContextChars` (was ambiguous vs tokens).
- `log.write` added for summary preview (was console-only).

---

## v8 — Data-driven context cap (planned)

Replace the hardcoded 64k ceiling with a per-model computed max safe transcript size
derived from perf store data. Benchmark regression on RAM/swap/pressure vs `transcriptChars`
already exists in mem0 — bring it in-script.

- **Regression fit per model**: solve for largest `transcriptChars` where
  `peakPressure` and `swap growth` stay under threshold. Fall back to current 64k hard
  cap when a model has insufficient data points (N < ? — TBD, probably 5).
- **Per-model overrides** in `MODELS` registry for models run at the edge or known
  outliers.
- **Benchmarking run mode**: scripted clean runs — pick specific session IDs, iterate
  across models, write to a separate perf log stream isolated from production summaries
  so training data stays clean.
- **Granular RAM logging** during input processing vs output processing if feasible
  (may need stream parsing to distinguish phases).

Difficulty: Medium. Data exists; mostly a curve fit + plumbing.

---

## v9 — Programmatic model launch (planned)

Launch models directly via `mlx-lm` instead of assuming LM Studio is pre-loaded.
Enables clean isolated runs and right-sized context per session.

- Shell out to `mlx-lm` with model path, context size, sampler params
- **Right-sized context per session**: using v8 regression data, pick the smallest
  context window that fits the upcoming transcript + safety margin. A 30k-char session
  doesn't need a 64k-token window loaded; smaller windows = less VRAM pressure = safer
  overnight batch runs regardless of system load.
- Model restart between benchmarking sessions (KV cache flush)
- **turboquant investigation**: shell out to turboquant CLI before mlx-lm launch,
  cache quantized output, load quantized model. Feasibility depends on whether the CLI
  surface supports this cleanly.
- Enables PARO model testing
- Monitor `preSessionIdleGb` vs `idleGb` for cooldown decisions; dynamic wait or bail
  and prompt user to restart the model if RAM doesn't settle

Difficulty: Hard (mlx-lm launch), Unknown (turboquant).

---

## v10 — Session chunking + merging (planned)

- **Chunking for oversize transcripts**: split at Claude compaction markers when present
  (compaction summaries already divide the session at natural breakpoints). Process the
  chunks through the summarizer and merge results.
  - **Do not use compaction summaries verbatim or as input to the summarizer** — they
    strip exactly the decisions/friction/mistakes/texture this pipeline exists to capture.
    Use them as anchors only.
  - For sessions without compaction markers, fall back to token-count windows with overlap.
  - Investigate: are we already using compaction markers as breakpoints implicitly?
- **Small-session merging**: merge or cross-reference summaries for adjacent small
  sessions that represent continuous interactions (timestamp proximity + topic overlap).
  Design depends on how the chunking pipeline resolves.
- Timestamp-anchored filtering for summary retrieval (filter by session start/end times
  to find sessions with carryover context).

Difficulty: Medium-Hard. Chunking design is the hard part; merging is I/O.

---

## v11 — Split benchmarking tool from prod summarizer (planned)

The script is currently both the benchmarking tool and the summarizer. Benchmarking
features (per-model perf tracking, runtime telemetry, context cap regression, multi-model
iteration) are growing; prod summarizer wants the opposite — one model, one pass, lean
code, minimal telemetry.

- **Branch or fork**: split into `mem0-benchmark` (keeps all the telemetry + multi-model
  infrastructure) and `mem0-summarizer` (stripped prod version)
- Prod summarizer migrates to AWS backend (DynamoDB + Lambda) replacing mem0
- Benchmark tool stays local, single-user, keeps evolving

Open question: branch in the current repo or new repo. Optics → new repo; simplicity →
branch. Decide at v11 planning time.

---

## Backlog / post-v11

- Quality scoring formalization (1–5 per session, stored in perf store alongside runtime
  metrics)
- Retry-on-fetch-fail with KV cache reuse: resend the same request on fetch failure to
  match the model's in-progress prefill cache. Lower priority now that timeout is 30 min.
  Open question: how long to wait before retry.
- Log file enrichment: match console output density (current log files are sparse vs
  the pretty console output)
- RAM warning tiers at model load (absorbed from old v8 plan, deprioritized):
  - Tier 1: "This model is large — close non-essential processes"
  - Tier 2: "Run `sudo [vram command]` for more headroom" when peak approaches system limit
- Interactive TUI for run configuration (session selection, model selection, flag
  selection). Deferred until CLI flag soup actually hurts usability.
- Unified log function for console + JSONL (currently rejected — formats differ too much,
  but worth revisiting if log enrichment lands)
- `getModelFailCap()` final removal once v8 regression cap ships
- **Empirical chars/token ratio**: replace flat 3.5 estimate with a per-model ratio
  derived from perf store (`transcriptChars / promptTokens` per run). Transcripts with
  heavy code or tool call JSON tokenize more efficiently than prose, so 3.5 can
  underestimate token count. Conservative percentile from observed runs would be more
  accurate than a hardcoded constant. Low priority until prod summarizer splits off.