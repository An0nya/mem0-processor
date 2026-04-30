import fs from "fs";
import { LLAMA_REGISTRY_PATH } from "./paths.mjs";

/** llama-server HTTP port. */
export const LLAMA_PORT = 8080;

/**
 * Loads and returns the models registry JSON. Throws if the file is missing.
 * @returns {object}
 */
export function loadLlamaRegistry() {
  if (!fs.existsSync(LLAMA_REGISTRY_PATH)) throw new Error(`Registry not found: ${LLAMA_REGISTRY_PATH}`);
  return JSON.parse(fs.readFileSync(LLAMA_REGISTRY_PATH, "utf8"));
}

const DEFAULT_REASONING_BUDGET = 4000;
const DEFAULT_REASONING_MAX_OUTPUT = 6000;
const DEFAULT_REASONING_BUDGET_MESSAGE =
  "[REASONING BUDGET EXHAUSTED]\nYour reasoning trace has reached its limit. Finalize your answer based on your analysis so far.";

/**
 * Resolves launch-time defaults for KV quant, sampler, maxOutputTokens, and reasoning budget.
 * Reasoning defaults only apply to models with reasoning.startString configured.
 * @param {object} entry - Registry entry for a model.
 * @returns {{ kvQuantK: string, kvQuantV: string, sampler: object, maxOutputTokens: number, reasoningBudget: number|null, reasoningBudgetMessage: string|null }}
 */
export function resolveLaunch(entry) {
  const kvDefault = entry.fileSizeGb < 8 ? "q8_0" : "q4_0";
  const isReasoningModel = !!entry.reasoning?.startString;
  return {
    kvQuantK: entry.launch.kvQuantK ?? kvDefault,
    kvQuantV: entry.launch.kvQuantV ?? kvDefault,
    sampler: { minP: 0.05, temp: 1.0, topK: 0, ...entry.sampler },
    maxOutputTokens: entry.launch.maxOutputTokens ?? (isReasoningModel ? DEFAULT_REASONING_MAX_OUTPUT : 4096),
    reasoningBudget: isReasoningModel ? (entry.launch.reasoningBudget ?? DEFAULT_REASONING_BUDGET) : null,
    reasoningBudgetMessage: isReasoningModel ? (entry.launch.reasoningBudgetMessage ?? DEFAULT_REASONING_BUDGET_MESSAGE) : null,
  };
}

/**
 * Builds the llama-server CLI flag array for the given registry entry.
 * @param {object} entry - Registry entry for a model.
 * @returns {string[]}
 */
export function buildLlamaFlags(entry) {
  const { kvQuantK, kvQuantV, sampler, reasoningBudget, reasoningBudgetMessage } = resolveLaunch(entry);

  const flags = [
    "-m", entry.path,
    "-c", String(entry.launch.ctxSize),
    "-ngl", String(entry.launch.nGpuLayers),
    "-ub", String(entry.launch.ubatchSize),
    "-ctk", kvQuantK,
    "-ctv", kvQuantV,
    "-t", String(entry.launch.threads),
    "--parallel", "1",
    "--port", String(LLAMA_PORT),
    "--min-p", String(sampler.minP),
    "--top-k", String(sampler.topK),
    "--temp", String(sampler.temp),
    "--prio", "2",
    "--cache-ram", "0",
  ];
  if (entry.chatTemplatePath) flags.push("--chat-template-file", entry.chatTemplatePath);
  if (entry.launch.flashAttn) flags.push("-fa", "on");
  if (entry.launch.nExpertsUsed) flags.push("--override-kv", `llm.expert_used_count=int:${entry.launch.nExpertsUsed}`);
  if (entry.launch.swaFull) flags.push("--swa-full");
  if (entry.sampler?.dynaTemp) flags.push("--dynatemp-range", String(entry.sampler.dynaTemp.range), "--dynatemp-exp", String(entry.sampler.dynaTemp.exp));
  if (reasoningBudget !== null) flags.push("--reasoning-budget", String(reasoningBudget));
  if (reasoningBudgetMessage !== null) flags.push("--reasoning-budget-message", reasoningBudgetMessage);
  return flags;
}
