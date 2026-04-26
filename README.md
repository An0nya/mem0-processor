# mem0-processor

Summarizes Claude Code session transcripts via a local LLM, then uploads the summaries to [Mem0](https://mem0.ai) as searchable memory. Also benchmarks model performance (RAM, tps, token counts) across runs.

## Prerequisites

- Node.js 18+
- A Mem0 API key
- For `--llama` mode: [llama-server](https://github.com/ggerganov/llama.cpp) on your PATH and a populated `config/models-registry.json`
- For LM Studio mode (default): [LM Studio](https://lmstudio.ai) running locally with a model loaded

## Setup

```bash
npm install
export MEM0_API_KEY=your_key_here
```

## Usage

### LM Studio mode (default)

Load a model in LM Studio, then run:

```bash
node claude-code-mem0-uploader.mjs
```

The script auto-detects whichever model is currently loaded.

### llama-server mode

```bash
node claude-code-mem0-uploader.mjs --llama <model-id>
```

`<model-id>` is a key from `config/models-registry.json` (fuzzy match). The script launches llama-server, runs the batch, then shuts it down.

In both modes the script discovers all Claude Code session files under `~/.claude/projects/`, summarizes any that haven't been processed yet, and uploads them to Mem0.

### Sweep mode

Run one or more sessions through multiple models (and optionally sampler presets) sequentially:

```bash
node sweep.mjs --session <id>[,<id>,...] --models <selectors> [--sampler <preset>] [--tag <name>] [--upload]
```

- `--session` — one or more session IDs or slugs, comma-separated
- `--models` — comma-separated selectors: `@<tag>`, `all`, `nvme`, `wd-elements`, exact key, or substring
- `--sampler` — named preset from `config/sampler-presets.json` (`default`, `conservative`, `hot`, `greedy`)
- `--tag` — run tag prefix; each run gets `<tag>-<si>.<mi>[.<pi>]`
- `--upload` — opt-in to mem0 upload (suppressed by default)

### Flags (uploader)

| Flag | Description |
|------|-------------|
| `--llama [id]` | Use llama-server instead of LM Studio. Optional model ID (fuzzy match on registry key); defaults to `qwen3.5-0.8b-unsloth-q8` if omitted. |
| `--no-upload` | Summarize only — skip the Mem0 write. Good for QA and benchmarking. |
| `--dry-run` | No uploads and no state changes. Prints what would happen. |
| `--reprocess [id]` | Bypass the "already done" check and regenerate the summary. Pass a session slug or UUID to reprocess one session, or omit to reprocess all. Existing cached summaries are archived before being overwritten. |
| `--no-token-cap` | Bypass the script's conservative 64k-token ceiling. Sessions are still limited by the model's actual loaded context window. |
| `--stream` | Stream LM Studio output token-by-token to the terminal instead of waiting for the full response. |
| `--llama-fresh` | Kill and relaunch llama-server between sessions to flush the KV cache. Useful for clean isolated benchmark runs. |
| `--sampler <preset>` | Apply a named sampler preset from `config/sampler-presets.json` to the API request. |
| `--run-tag <name>` | Tag all perf entries from this run. Lets benchmark runs be filtered cleanly from ad-hoc runs in the perf store. |

### Examples

```bash
# Normal run — process and upload anything new (LM Studio)
node claude-code-mem0-uploader.mjs

# llama-server run with a specific model
node claude-code-mem0-uploader.mjs --llama gemma-4-26b

# Benchmark run — summarize everything fresh, no upload
node claude-code-mem0-uploader.mjs --llama qwen3.5-0.8b --reprocess --no-upload --run-tag sweep

# Re-summarize one session
node claude-code-mem0-uploader.mjs --llama gemma-4-26b --reprocess piped-leaping-eagle

# Sweep two sessions across all nvme models with a sampler preset
node sweep.mjs --session piped-leaping-eagle,woolly-pondering-glacier --models @nvme --sampler conservative --tag apr-sweep
```

## What gets written where

| Path | Contents |
|------|----------|
| `~/.claude/mem0/state/<model>.json` | Per-model record of which sessions have been summarized and uploaded |
| `~/.claude/mem0/summaries/<slug>--<session8>--<model>.txt` | Cached summary text (reused on subsequent runs unless `--reprocess`). Multi-part sessions (compaction splits) append `-partN`. Includes a YAML frontmatter block with session + launch + perf metadata. |
| `~/.claude/mem0/summaries/archive/<slug>/<session>--<timestamp>.txt` | Archived copies of summaries overwritten by `--reprocess` |
| `~/.claude/mem0/transcripts/<slug>--<session8>.txt` | Cached rendered transcript as sent to the summarizer. Reused on reruns; overwritten by `--reprocess`. |
| `~/.claude/mem0/compaction-summaries/<sessionId>-<n>.md` | Extracted compaction summaries cached per session. |
| `~/.claude/mem0/logs/<timestamp>--<model>.jsonl` | Per-run log of session outcomes (tps, RAM, token counts, skips, errors) |
| `~/.claude/mem0/logs/llama-server-<timestamp>.log` | Raw llama-server stdout/stderr for each launch |
| `~/.claude/mem0/perf.json` | Append-only perf store: one entry per summarization with idle/peak/avg RAM, swap, memory pressure, tps, prefill tps, token counts, transcript length, launch params |

State files and summary caches are per-model intentionally — the same sessions can be run through multiple models for benchmarking without colliding.

## Adding a model

### LM Studio mode

Any model loaded in LM Studio is auto-detected — no configuration needed. The script reads the active model from the LM Studio API at startup.

### llama-server mode

Add an entry to `config/models-registry.json`:

```json
"your/model-slug": {
  "path": "/Volumes/NVMe External/models/your-model.gguf",
  "fileSizeGb": 8.5,
  "format": "gguf",
  "arch": "qwen3",
  "source": "nvme",
  "chatTemplatePath": "/Users/you/.claude/mem0/templates/qwen.jinja",
  "launch": {
    "ctxSize": 32000,
    "nGpuLayers": -1,
    "ubatchSize": 512,
    "flashAttn": true,
    "threads": 8
  }
}
```

Metadata fields (`nLayer`, `nCtxTrain`, `modelType`, `modelParams`, `quantType`, `bpw`) are auto-populated from the llama-server log on the first successful run. To backfill from existing logs, run `node tools/backfill-registry-meta.mjs`. To auto-derive tags from registry fields, run `node tools/backfill-registry-tags.mjs`.

## Context limits

The script uses two ceilings, whichever is smaller:

- **Model ceiling**: the model's loaded context window, converted to chars at 3.5 chars/token.
- **Script ceiling**: a conservative hard cap of 64k tokens (~224k chars). Bypass with `--no-token-cap`.

Sessions exceeding the effective limit are skipped with a warning. Chunking for oversized transcripts is planned for v10.

## Utility scripts (`tools/`)

| Script | Purpose |
|--------|---------|
| `tools/backfill-registry-meta.mjs` | Import model metadata from existing llama-server logs into the registry. Dry-run by default; `--write` to apply. |
| `tools/backfill-registry-perf.mjs` | Compute per-model memory/performance statistics from `perf.json` and write them back to the registry. |
| `tools/backfill-registry-tags.mjs` | Auto-derive `tags[]` from existing registry fields. Fill-missing, re-runnable. |
| `tools/mem0-migrate.mjs` | Migration utility for mem0 data. |
| `tools/build-dataset.py` | Build a SQLite dataset from summaries, perf data, registry metadata, and session scoring scripts. Requires Python 3. |

## Quality scoring (`scoring/`)

Per-session Python scripts that score summary quality against hand-written ground-truth fact sets. Used to evaluate model and sampler combinations. Run individually or consumed by `tools/build-dataset.py`.
