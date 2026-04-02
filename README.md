# mem0-processor

Summarizes Claude Code session transcripts via a local or cloud LLM, then uploads the summaries to [Mem0](https://mem0.ai) as searchable memory. Also benchmarks model performance (RAM, tps, token counts) across runs.

## Prerequisites

- Node.js 18+
- [LM Studio](https://lmstudio.ai) running locally (for local models), or an Anthropic API key (for `claude-haiku`)
- A Mem0 API key

## Setup

```bash
npm install
export MEM0_API_KEY=your_key_here
```

## Usage

Load a model in LM Studio, then run:

```bash
node claude-code-mem0-uploader.mjs
```

The script auto-detects whichever model is currently loaded. It discovers all Claude Code session files under `~/.claude/projects/`, summarizes any that haven't been processed yet, and uploads them to Mem0.

### Flags

| Flag | Description |
|------|-------------|
| `--no-upload` | Summarize only — skip the Mem0 write. Good for QA and benchmarking. |
| `--dry-run` | No uploads and no state changes. Prints what would happen. |
| `--reprocess [id]` | Bypass the "already done" check. Pass a session UUID to reprocess one session, or omit the ID to reprocess all. |
| `--model <query>` | Load a specific model by partial ID match (e.g. `--model qwen3`). Defaults to whatever LM Studio has loaded. |
| `--force-truncate` | Process sessions that exceed the context limit by truncating them instead of skipping. |

### Examples

```bash
# Normal run — process and upload anything new
node claude-code-mem0-uploader.mjs

# Benchmark run — summarize everything fresh, no upload
node claude-code-mem0-uploader.mjs --reprocess --no-upload

# Re-summarize one session with a specific model
node claude-code-mem0-uploader.mjs --reprocess abc123 --model qwen3

# Use Claude Haiku instead of a local model
node claude-code-mem0-uploader.mjs --model haiku
```

## What gets written where

| Path | Contents |
|------|----------|
| `~/.claude/mem0_upload_state--<model>.json` | Per-model record of which sessions have been summarized and uploaded |
| `~/.claude/mem0_summaries/<session>--<model>.txt` | Cached summary text (reused on subsequent runs unless `--reprocess`) |
| `~/.claude/mem0_logs/<timestamp>--<model>.jsonl` | Per-run log of session outcomes (tps, RAM, token counts, skips, errors) |
| `~/.claude/mem0_model_perf.json` | Append-only perf store: one entry per summarization with idle/peak/avg RAM, tps, token count, transcript length |

State files and summary caches are per-model intentionally — the same sessions can be run through multiple models for benchmarking without colliding.

## Adding a model

Add an entry to the `MODELS` array at the top of the script:

```js
{ id: "your-model-id-as-lmstudio-reports-it", provider: "lmstudio" },
```

For Anthropic models, use `provider: "anthropic"` and the exact model ID. Any model loaded in LM Studio that isn't in the registry will still work — the script will warn and assume `lmstudio` provider.

## Context limits

The script fetches `max_context_length` from the LM Studio v0 API and uses it as a hard ceiling (converting tokens → chars at 3.5 chars/token). Sessions exceeding the limit are skipped unless `--force-truncate` is passed.

Models with a historically observed peak RAM above 12 GB (per the perf store) get an additional cap of ~32k tokens to limit KV cache pressure.
