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
| `--reprocess [id]` | Bypass the "already done" check and regenerate the summary from the LLM. Pass a session UUID to reprocess one session, or omit the ID to reprocess all. Existing cached summaries are archived before being overwritten. |
| `--model <query>` | Load a specific model by partial ID match (e.g. `--model qwen3`). Defaults to whatever LM Studio has loaded. |
| `--no-token-cap` | Bypass the script's conservative 64k-token ceiling. Sessions are still limited by the model's actual loaded context window. |
| `--stream` | Stream LM Studio output token-by-token to the terminal instead of waiting for the full response. |

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
| `~/.claude/mem0/state/<model>.json` | Per-model record of which sessions have been summarized and uploaded |
| `~/.claude/mem0/summaries/<session>--<model>.txt` | Cached summary text (reused on subsequent runs unless `--reprocess`) |
| `~/.claude/mem0/summaries/archive/<slug>/<session>--<timestamp>.txt` | Archived copies of summaries overwritten by `--reprocess` |
| `~/.claude/mem0/logs/<timestamp>--<model>.jsonl` | Per-run log of session outcomes (tps, RAM, token counts, skips, errors) |
| `~/.claude/mem0/perf.json` | Append-only perf store: one entry per summarization with idle/peak/avg RAM, swap, memory pressure, tps, prefill tps, token counts, transcript length |

State files and summary caches are per-model intentionally — the same sessions can be run through multiple models for benchmarking without colliding.

## Adding a model

Add an entry to the `MODELS` array at the top of the script:

```js
{ id: "your-model-id-as-lmstudio-reports-it", provider: "lmstudio" },
```

For Anthropic models, use `provider: "anthropic"` and the exact model ID. Any model loaded in LM Studio that isn't in the registry will still work — the script will warn and assume `lmstudio` provider.

## Context limits

The script uses two ceilings, whichever is smaller:

- **Model ceiling**: the model's loaded context window from the LM Studio API, converted to chars at 3.5 chars/token.
- **Script ceiling**: a conservative hard cap of 64k tokens (~224k chars). Bypass with `--no-token-cap`.

Sessions exceeding the effective limit are skipped with a warning. Chunking for oversized transcripts is planned for v10.
