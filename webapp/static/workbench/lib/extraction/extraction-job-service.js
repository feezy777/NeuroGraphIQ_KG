import { runPlaceholderExtraction } from "./extraction-placeholder-engine.js";
import { getGranularityOption, getGranularityTableMapping } from "./granularity-config.js";
import { resolveRuntimeMode } from "./extraction-mode-config.js";
import { sanitizeDeepSeekConfig, toDeepSeekJobSummary } from "./deepseek-default-config.js";

function now() {
  return new Date().toISOString();
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export function createExtractionJob({
  ontologyId,
  fileIds,
  targets,
  mode,
  output,
  granularity = "coarse",
  tableMapping = null,
  deepseekConfig = null,
}) {
  const option = getGranularityOption(granularity);
  const deepseekSafe = sanitizeDeepSeekConfig(deepseekConfig || {});
  const runtimeMode = resolveRuntimeMode(deepseekSafe.enabled);

  return {
    id: `job_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    status: "queued",
    mode,
    runtimeMode,
    output,
    targets,
    fileIds,
    ontologyId,
    granularity: option.id,
    tableMapping: tableMapping || getGranularityTableMapping(option.id),
    deepseek: toDeepSeekJobSummary(deepseekSafe),
    createdAt: now(),
    startedAt: "",
    finishedAt: "",
    progress: 0,
    stage: "queued",
  };
}

export async function runExtractionJob(job, context, hooks = {}) {
  const { onProgress, onComplete, onError } = hooks;
  try {
    onProgress?.({ ...job, status: "running", progress: 10, stage: "prepare_inputs", startedAt: now() });
    await delay(350);

    const extractStage = job.runtimeMode === "deepseek" ? "deepseek_mock_extract" : "placeholder_extract";
    onProgress?.({ ...job, status: "running", progress: 45, stage: extractStage });
    await delay(450);

    const result = runPlaceholderExtraction({
      ontology: context?.ontology,
      files: context?.files,
      targets: job.targets,
      mode: job.mode,
      runtimeMode: job.runtimeMode,
      output: job.output,
      granularity: job.granularity,
      tableMapping: job.tableMapping,
      deepseek: job.deepseek,
    });

    onProgress?.({ ...job, status: "running", progress: 80, stage: "build_candidates" });
    await delay(280);

    const done = {
      ...job,
      status: "succeeded",
      progress: 100,
      stage: "finished",
      startedAt: job.startedAt || now(),
      finishedAt: now(),
    };
    onComplete?.(done, result);
    return { job: done, result };
  } catch (error) {
    const failed = {
      ...job,
      status: "failed",
      stage: "error",
      finishedAt: now(),
      error: String(error),
    };
    onError?.(failed, error);
    throw error;
  }
}
