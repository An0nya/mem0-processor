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

## v7.3 — Transcript quality + session structure (in progress)

Patch before v8. Improves signal fidelity in transcripts fed to summarizer models.
No new flags or config; all changes are internal to transcript building and session handling.

**Shipped:** tool label differentiation, thinking traces, slug-based IDs, transcript
cache, tier 1 + tier 2 session filters, post-session telemetry, cache hit classifier,
prompt iteration 4.
**Remaining:** compaction extraction + session splitting, session chaining/merging,
chronological session ordering.

### Tool label differentiation

Current `[TOOL_ERROR]` covers three distinct events that summarizer models conflate:
- **User denial**: `is_error: true` + content contains "The user doesn't want to proceed"
  → emit `[TOOL_DENIED: <reason>]`. Reason extracted from after "The user provided the
  following reason for the rejection:" if present, otherwise just `[TOOL_DENIED]`.
- **Auto-approved**: tool_call immediately followed by tool_result with no intervening
  user turn (always-allow or implicit harness approval) → emit `[TOOL_AUTO]` prefix on
  result line so models can distinguish supervised from unsupervised execution.
- **Genuine error**: `is_error: true` but not a denial → keep `[TOOL_ERROR]`.

Prepend a legend block to the transcript before sending to the summarizer so models don't
have to infer label meaning:
```
[TRANSCRIPT FORMAT: TOOL_AUTO = no user approval required OR user approved action type globally previously; TOOL_DENIED = user explicitly rejected; TOOL_ERROR = execution failed; TOOL_CALL/TOOL_RESULT = standard supervised tool use; THINKING = model extended reasoning trace]
```
Legend travels with the transcript regardless of model or prompt version.

### Extended thinking traces

`type=thinking` content blocks in assistant messages were previously silently dropped.
They contain the model's full reasoning before a response — useful signal for summarizers
(shows *why* a decision was made, not just what was done) and a complexity indicator
(presence of thinking blocks = extended thinking was invoked on that turn).

Emit as `[THINKING]\n<full text>\n[/THINKING]` — no truncation. Thinking traces are
bounded by the model's reasoning budget; they don't inflate unboundedly. Summarizer
models handle them well when clearly delineated.

`type=thinking` blocks also carry a `signature` field (opaque token) — ignored in output.

### Compaction summary extraction + local cache

Compaction data appears in two places — one reliable, one inconsistent:

**Primary (always present):** `type=user, isCompactSummary=true` entries in the main
session JSONL. Each compaction produces a `type=system, subtype=compact_boundary` entry
immediately followed by a `type=user, isCompactSummary=true` entry containing the full
summary text. This pair is always written regardless of compaction method. Use the
`compact_boundary` timestamp as the split point.

**Secondary (present in some sessions only):** `subagents/agent-acompact-<id>.jsonl`
files alongside the main session file. Not generated for all compactions — confirmed
absent for at least two sessions (ef0cad9d, 06a657b2) that have inline summaries. When
present, the last `type=assistant` entry contains `<analysis>` + `<summary>` blocks.
The `<analysis>` block is the model's reasoning about what to preserve — potentially
useful for quality scoring or surfacing what the model considered load-bearing context.
Files where the last entry is `type=user` = incomplete run, skip.

Implementation:
- Scan main JSONL for `isCompactSummary=true` entries — use these as the reliable source
- Also scan for `agent-acompact-*` files; if present, extract `<analysis>` and `<summary>`
- Cache inline summary as `~/.claude/mem0/compaction-summaries/<sessionId>-<compactIndex>.md`
- If acompact file also exists for that compaction, cache analysis separately or append
- Check for cached file before re-extracting; no mem0 upload yet

### Transcript cache

After building the rendered transcript string (post-tool-label processing, post-split,
post-legend prepend), write it to `~/.claude/mem0/transcripts/<slug>--<sessionId>.txt`
before sending to the summarizer.

- Check for cached file before rebuilding; skip JSONL re-parse on reruns
- On `--reprocess`, overwrite (same semantics as summary cache)
- Enables comparison of transcript vs. summary output for quality evaluation
- No format changes to the transcript itself; cache is the string as-sent

### Post-session telemetry + cache hit classifier

**Status: shipped.**

After each session completes summarization, sample RAM and swap again:
- `postSessionIdleGb` — GPU-wired RAM after inference completes
- `postSessionSwap` — swap after inference completes
- Both stored in perf entry alongside existing `preSessionIdleGb`

`classifyCacheHit(perfStore, modelId, { promptTokens, ttft })` — new function that
infers whether the model reused a KV cache hit from a recent run:
- Looks up the last 20 non-failed runs for the model within a 30-minute window
- Classifies as 'definite' (prefillTps > 2000 + matching token count), 'likely',
  'possible', or 'none'. Returns 'unknown' if data is insufficient.
- `cacheHit` stored in perf entry; useful for interpreting anomalously fast prefill TPS.

Also added per-run:
- `runIndexInBatch` — position of this session within the current script run (0-indexed,
  increments on both success and failure)
- `timeSinceLastRunMin` — minutes since the model's last perf store entry; useful for
  gauging KV cache staleness and cooldown behavior between benchmark runs

Fix: summary timestamp prepend and `saveCachedSummary` call were being called *after*
the summary preview print, meaning the cached file was missing the timestamp header on
the first write. Reordered so cache write happens before preview.

### Summarization prompt — iteration 4

**Status: shipped.**

Revision focused on precision and attribution accuracy (shipped alongside telemetry
expansion):
- Added MISCOMMUNICATION label to Mistakes & Overreach (previously ERROR + OVERREACH only)
- Friction Points: added explicit instruction to explain significance/consequence of each
  friction event, not just classify it
- [USER-APPROVED] vs [USER-CLARIFIED] distinction expanded with explicit counterexample
  inline: if user asked first then accepted, that's [USER-CLARIFIED], not [USER-APPROVED]
- [CLAUDE-UNPROMPTED] distinction tightened: explicit instruction not to use it when
  Claude was asked; default to [CLAUDE-UNPROMPTED] when uncertain
- Open Threads: restructured to require (a) what's incomplete, (b) concrete next action,
  (c) what needs to be true to close it; and to distinguish deferred/unstarted/unverified
- Competence & Clarifications: added instruction to explain how each conclusion was reached
- Confident-framing flag: now requires pointing to a specific turn, not a general pattern
- Framing shifted from "summary" to "audit" / "process-level analysis"

Also: `msg.reasoning_content ?? msg.reasoning` fallback added to LM Studio response parse
(gpt-oss uses `reasoning` field instead of `reasoning_content`).

### Session splitting at compaction breakpoints

When a session has `compact_boundary` entries, split the main transcript at each one:

- Pre-compaction segment: processed normally as its own transcript chunk
- Post-compaction segment: `isCompactSummary=true` text prepended as `[PRIOR CONTEXT]`
  header, then remaining entries. Models get oriented without reading the full prior segment.
- Multiple compactions = multiple splits; each post-compaction chunk uses most recent summary
- Split point is the `compact_boundary` timestamp (always present; no dependency on acompact files)
- Partially implements v10 chunking for compacted sessions. v10 still owns the fallback
  (non-compacted oversize sessions) and small-session merging.

### Slug-based session identification

Every JSONL entry has a `slug` field (e.g. `"woolly-pondering-glacier"`). UUIDs are
unreadable in logs and filenames.

- Extract slug from first entry with a non-null `slug` field
- Use `<slug>--<sessionId-prefix>` in output filenames and log lines (UUID prefix keeps
  uniqueness; slug adds readability)
- Archive paths already use slug; ensure consistency across all references

### Session chaining + merging

Adjacent sessions sharing CWD + close timestamps are likely continuous work. Two
mechanisms, same investigation dependency:

**Cross-session context injection**: when a session follows a recent one (same CWD,
gap < threshold), prepend the previous session's last assistant message or compaction
summary (whichever is more recent) as `[PREV SESSION CONTEXT]` header. Same mechanic as
`[PRIOR CONTEXT]` for post-compaction segments — ~5 lines of difference once that exists.
Defer until compaction injection exists.

**Small-session merging**: sessions too short to summarize individually (currently skipped
at 500-char minimum) may have a throughline. If back-to-back and same CWD, merge with a
`[SESSION BREAK]` marker; merged transcript gets one summary pass.

> **Testing note**: the 500-char `too_short` check runs on the *built* transcript
> (post-merge). If a merged cluster still lands under 500 chars it was probably merged
> junk and the skip is correct. Verify during merge testing that the threshold still
> makes sense at that stage, or tune it.

**Useless session filtering** (prerequisite for merging — no point including noise):
- Hard skip: no `type=user` or `type=assistant` entries with non-empty, non-meta text.
  Covers teleport stubs, queue-operation-only sessions, isMeta-only sessions.
- Soft skip: user-side text ≤ ~20 chars AND no tool calls. Covers `claude "help"` →
  generic response cases where assistant boilerplate inflates combined char count
  deceptively. Measure user-side text separately; do not rely on combined char count.

**Heuristic (investigated, resolved)**: CWD + timestamp gap is sufficient — no need for
semantic matching. Gap threshold: ~15 minutes captures contiguous incident clusters
without false positives. Walk forward greedily from the first sub-threshold session;
only pull in sub-threshold neighbors. Do not absorb adjacent large sessions — they
summarize independently and supply context through normal processing.

Example — enter-key keybinding incident (`~/.claude/projects/-Users-anya/`, 2026-03-26):
```
03:32  27f6e18b  2237 chars  "how to resume a session"      above threshold → own summary
03:43  049225b0   468 chars  claude "help" (4 user chars)   soft-skip / merge candidate
03:47  b74252b3   100 chars  tool call, interrupted          merge candidate
03:48  d19d5c64   316 chars  keybindings attempt, cut        merge candidate
03:50  4ba5521d  1565 chars  Enter → newline keybinding      above threshold → own summary
```
Three sub-threshold sessions merged = 884 chars, gap 03:43–03:48 = 5 min. Narrative:
*Enter broken → tried `claude "help"` from terminal → two interrupted keybinding attempts*.
Parent session `888373a7` (01:26–04:14, 60 user turns) covers the full incident including
the disaster and recovery; the merged cluster adds granularity on the frantic middle.

**Implementation order**:
1. Hard-skip filter — check for absent user/assistant text; trivial
2. Soft-skip filter — measure user-side char count separately; flag ≤ 20 chars + no tool calls
3. Small-session merge — CWD match + gap ≤ 15 min + sub-threshold; greedy forward walk
4. Cross-session context injection — defer until compaction injection (step above) exists

**Transcript variables to evaluate** (once injection infrastructure exists — A/B as toggles):
- Per-turn timestamps in transcript entries — signal vs. noise for summarizer models, unknown
- Compaction summary as `[PRIOR CONTEXT]` — planned for v7.3
- Previous session summary as `[PREV SESSION CONTEXT]` — planned for v7.3
- Changelog/roadmap injection — orients the model vs. biases it toward known topics?
- Combos: compaction + prev session, timestamps + context header, etc.

**Held / ruled out**:
- Legend block in system prompt — ruled out; goes in transcript body for model/prompt portability

Difficulty: Low (tool labels, slug, filter tiers 1–2), Medium (compaction extraction +
split, session merge), Medium (context injection — depends on compaction work landing first).

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

## v10 — Fallback chunking for oversize sessions (planned)

v7.3 handles compacted sessions (split at compaction markers, context injection at
boundaries, small-session merging). v10 handles the remaining hard case: sessions that
are oversize AND have no compaction markers.

- **Fallback chunking**: split at token-count windows with overlap when no compaction
  anchor exists. Process chunks through the summarizer and merge results.
- Timestamp-anchored filtering for summary retrieval (filter by session start/end times
  to find sessions with carryover context).

Difficulty: Medium-Hard. Chunking design is the hard part.

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
- **Chronological session ordering**: sessions currently processed in filesystem inode
  order. Sort by session `startedAt` before the inference loop so batch runs and logs
  read in actual temporal order. Low-effort; fits v7.3 session structure work.
- **Inference settings per run**: log temperature, top_p, repeat_penalty, min_p, etc.
  to the perf store alongside runtime telemetry. Not viable until v9 programmatic launch
  — sampler params aren't returned in API responses and manual injection per model would
  be fragile. Defer to v9.
- **Empirical chars/token ratio**: replace flat 3.5 estimate with a per-model ratio
  derived from perf store (`transcriptChars / promptTokens` per run). Transcripts with
  heavy code or tool call JSON tokenize more efficiently than prose, so 3.5 can
  underestimate token count. Conservative percentile from observed runs would be more
  accurate than a hardcoded constant. Low priority until prod summarizer splits off.