import { execSync } from "child_process";

/** GPU wired memory budget from iogpu.wired_limit_mb, in GB. Returns null on failure. */
export function gpuBudgetGb() {
  try {
    const raw = execSync("sysctl iogpu.wired_limit_mb", { encoding: "utf8" });
    const match = raw.match(/iogpu\.wired_limit_mb:\s*(\d+)/);
    if (!match) return null;
    return +(parseInt(match[1], 10) / 1024).toFixed(2);
  } catch { return null; }
}

/** GPU allocated system memory via AGXAccelerator ioreg, in GB. Returns null on failure. */
export function gpuAllocGb() {
  try {
    const raw = execSync("ioreg -r -c AGXAccelerator -d 2", { encoding: "utf8" });
    const match = raw.match(/"Alloc system memory"=(\d+)/);
    if (!match) return null;
    return +(parseInt(match[1], 10) / 1e9).toFixed(2);
  } catch { return null; }
}

/** Current swap used via sysctl vm.swapusage, in GB. Returns null on failure. */
export function swapUsedGb() {
  try {
    const raw = execSync("sysctl vm.swapusage", { encoding: "utf8" });
    const match = raw.match(/used\s*=\s*([\d.]+)([KMG])/);
    if (!match) return null;
    const val = parseFloat(match[1]);
    const unit = match[2];
    return +(val / (unit === "G" ? 1 : unit === "M" ? 1024 : 1048576)).toFixed(3);
  } catch { return null; }
}

/** Memory pressure as used% (100 - free%). Returns null on failure. */
export function memPressureLevel() {
  try {
    const raw = execSync("memory_pressure", { encoding: "utf8" });
    const match = raw.match(/System-wide memory free percentage:\s*(\d+)%/);
    if (!match) return null;
    return 100 - parseInt(match[1], 10);
  } catch { return null; }
}

/**
 * Starts a background sampler that polls GPU alloc, swap, and memory pressure.
 * @param {number} intervalMs - Polling interval in ms (default 500).
 * @returns {{ stop: () => object }} Call stop() to end sampling and get aggregates.
 */
export function startRamSampler(intervalMs = 500) {
  const allocRamSamples = [];
  const swapSamples = [];
  const pressureSamples = [];
  const interval = setInterval(() => {
    const gb = gpuAllocGb();
    if (gb !== null) allocRamSamples.push(gb);
    const swap = swapUsedGb();
    if (swap !== null) swapSamples.push(swap);
    const pressure = memPressureLevel();
    if (pressure !== null) pressureSamples.push(pressure);
  }, intervalMs);
  return {
    stop() {
      clearInterval(interval);
      if (allocRamSamples.length === 0) return { peakUsedGb: null, avgUsedGb: null };
      const allocPeak = Math.max(...allocRamSamples);
      const allocAvg  = allocRamSamples.reduce((a, b) => a + b, 0) / allocRamSamples.length;
      const startingSwap = Math.min(...swapSamples);
      const swapMax = Math.max(...swapSamples);
      const swapAvg = swapSamples.reduce((a, b) => a + b, 0) / swapSamples.length;
      const pressurePeak = Math.max(...pressureSamples);
      const pressureAvg = pressureSamples.reduce((a, b) => a + b, 0) / pressureSamples.length;
      return {
        peakUsedGb:   +allocPeak.toFixed(2),
        avgUsedGb:    +allocAvg.toFixed(2),
        startingSwap: +startingSwap.toFixed(2),
        maxSwap:      +swapMax.toFixed(2),
        avgSwap:      +swapAvg.toFixed(3),
        peakPressure: +pressurePeak,
        pressureAvg:  +pressureAvg.toFixed(2),
      };
    },
  };
}

/**
 * Prints the end-of-run stats table to stdout.
 * @param {{ id: string }} model
 * @param {{ loaded_context_length?: number, quantization?: string }|null} modelInfo
 * @param {object[]} stats - Per-session perf entries accumulated during the run.
 */
export function printSummary(model, modelInfo, stats) {
  const ttftSamples = stats.filter((s) => s.ttft != null).map((s) => s.ttft);
  const genTimeSamples = stats.filter((s) => s.genTime != null).map((s) => s.genTime);

  const tpsSamples = stats.filter((s) => s.tps != null).map((s) => s.tps);
  const prefillSamples = stats
    .filter((s) => s.prefillTps != null)
    .map((s) => parseFloat(s.prefillTps));
  const ramSamples = stats.filter((s) => s.peakUsedGb != null);
  const swapSamples = stats.filter((s) => s.maxSwap != null);
  const pressureSamples = stats.filter((s) => s.peakPressure != null);

  const totalPrefillTime = ttftSamples.reduce((a, s) => a + s, 0);
  const totalGenTime = genTimeSamples.reduce((a, s) => a + s, 0);
  const totalRuntime = totalPrefillTime + totalGenTime;

  const avgTps    = tpsSamples.length ? (tpsSamples.reduce((a, b) => a + b, 0) / tpsSamples.length).toFixed(1) : "n/a";
  const peakTps   = tpsSamples.length ? Math.max(...tpsSamples).toFixed(1) : "n/a";
  const minTps    = tpsSamples.length ? Math.min(...tpsSamples).toFixed(1) : "n/a";
  const avgPrefill  = prefillSamples.length ? (prefillSamples.reduce((a, b) => a + b, 0) / prefillSamples.length).toFixed(1) : "n/a";
  const peakPrefill = prefillSamples.length ? Math.max(...prefillSamples).toFixed(1) : "n/a";
  const minPrefill  = prefillSamples.length ? Math.min(...prefillSamples).toFixed(1) : "n/a";

  const peakRam = ramSamples.length ? Math.max(...ramSamples.map((s) => s.peakUsedGb)).toFixed(2) : "n/a";
  const avgRam  = ramSamples.length
    ? (ramSamples.reduce((a, b) => a + b.avgUsedGb, 0) / ramSamples.length).toFixed(2)
    : "n/a";

  const maxPressure = pressureSamples.length ? Math.max(...pressureSamples.map((s) => s.peakPressure)).toFixed(2) : "n/a";
  const avgPressure = pressureSamples.length
    ? (pressureSamples.reduce((a, b) => a + b.pressureAvg, 0) / pressureSamples.length).toFixed(2)
    : "n/a";

  const peakSwap = swapSamples.length ? Math.max(...swapSamples.map((s) => s.maxSwap)).toFixed(2) : "n/a";
  const avgSwap  = swapSamples.length && swapSamples.some(s => s.avgSwap != null)
    ? (swapSamples.filter(s => s.avgSwap != null).reduce((a, b) => a + b.avgSwap, 0) / swapSamples.filter(s => s.avgSwap != null).length).toFixed(2)
    : "n/a";

  const totalTokens     = stats.filter((s) => s.completionTokens).reduce((a, s) => a + s.completionTokens, 0);
  const totalInputToks  = stats.filter((s) => s.promptTokens).reduce((a, s) => a + s.promptTokens, 0);
  const totalInputChars = stats.filter((s) => s.inputChars).reduce((a, s) => a + s.inputChars, 0);
  const contextLen = modelInfo?.loaded_context_length ? `${(modelInfo.loaded_context_length / 1000).toFixed(0)}k` : "unknown";
  const quant      = modelInfo?.quantization ?? "unknown";

  console.log(`
─────────────────────────────────────────────────────
Model:           ${model.id}
Context:         ${contextLen}   Quant: ${quant}
─────────────────────────────────────────────────────
Sessions:        ${stats.filter((s) => !s.skipped && !s.error).length} processed  │  ${stats.filter((s) => s.skipped).length} skipped  │  ${stats.filter((s) => s.error).length} errors
Tokens:          ${totalInputToks} total input tokens  (total input chars: ${totalInputChars}, overall chars/tok: ${(totalInputChars/totalInputToks).toFixed(2)})  |  ${totalTokens} total output tokens
Runtime:         total ${totalRuntime.toFixed(2)}s  |  prefill ${totalPrefillTime.toFixed(2)}s  |  gen ${totalGenTime.toFixed(2)}s
   ---
Output tok/s:    avg ${avgTps}  │  peak ${peakTps}  │  min ${minTps}
Prefill tok/s:   avg ${avgPrefill}  |  peak ${peakPrefill}  |  min ${minPrefill}
   ---
RAM (sys):       peak ${peakRam} GB  │  avg ${avgRam} GB
Swap (sys):      peak ${peakSwap} GB  |  avg ${avgSwap} GB
Memory Pressure: peak ${maxPressure}%  |  avg ${avgPressure}%
─────────────────────────────────────────────────────`);
}
