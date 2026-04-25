import path from "path";
import os from "os";

/** Root of all mem0 data written by this tool. */
export const MEM0_DIR = path.join(os.homedir(), ".claude", "mem0");

/** Claude Code project directories (source of session .jsonl files). */
export const PROJECTS_DIR = path.join(os.homedir(), ".claude", "projects");

/** Markdown summaries written after each session. */
export const SUMMARIES_DIR = path.join(MEM0_DIR, "summaries");

/** Archive subdirectory for rotated summaries. */
export const ARCHIVE_DIR = path.join(SUMMARIES_DIR, "archive");

/** Run logs (.jsonl, one per invocation). */
export const LOGS_DIR = path.join(MEM0_DIR, "logs");

/** Cached transcript files (.md). */
export const TRANSCRIPTS_DIR = path.join(MEM0_DIR, "transcripts");

/** Append-only performance store. */
export const PERF_STORE_PATH = path.join(MEM0_DIR, "perf.json");

/** Extracted compaction summaries from session logs. */
export const COMPACTION_SUMMARIES_DIR = path.join(MEM0_DIR, "compaction-summaries");

/** Raw llama-server response dumps (kept until timings are fully wired). */
export const LLAMA_RESPONSES_DIR = path.join(MEM0_DIR, "llama-responses");

/** Absolute path to the model registry JSON, resolved relative to this repo. */
export const LLAMA_REGISTRY_PATH = new URL("../config/models-registry.json", import.meta.url).pathname;
