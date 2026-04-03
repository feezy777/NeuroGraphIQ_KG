import { createStore } from "./create-store.js";
import { getGranularityOption, getGranularityTableMapping } from "../lib/extraction/granularity-config.js";
import { createDefaultDeepSeekConfig, sanitizeDeepSeekConfig } from "../lib/extraction/deepseek-default-config.js";

const store = createStore({
  jobs: [],
  activeJobId: "",
  resultByJobId: {},
  draft: {
    mode: "placeholder_balanced",
    output: "triples",
    targets: ["region", "circuit", "connection"],
    granularity: "coarse",
    tableMapping: getGranularityTableMapping("coarse"),
    deepseek: createDefaultDeepSeekConfig(),
  },
});

export const extractionStore = {
  ...store,
  addJob(job) {
    store.setState((state) => ({
      jobs: [job, ...state.jobs],
      activeJobId: job.id,
    }));
  },
  updateJob(jobId, patch) {
    store.setState((state) => ({
      jobs: state.jobs.map((job) => (job.id === jobId ? { ...job, ...(patch || {}) } : job)),
    }));
  },
  setJobResult(jobId, result) {
    store.setState((state) => ({
      resultByJobId: {
        ...state.resultByJobId,
        [jobId]: result,
      },
      activeJobId: jobId,
    }));
  },
  setActiveJob(jobId) {
    store.setState({ activeJobId: jobId || "" });
  },
  updateDraft(patch) {
    store.setState((state) => ({
      draft: {
        ...state.draft,
        ...(patch || {}),
      },
    }));
  },
  setGranularity(granularity) {
    const option = getGranularityOption(granularity);
    store.setState((state) => ({
      draft: {
        ...state.draft,
        granularity: option.id,
        tableMapping: { ...option.tableMapping },
      },
    }));
  },
  setGranularityFromDefault(granularity) {
    const option = getGranularityOption(granularity);
    store.setState((state) => ({
      draft: {
        ...state.draft,
        granularity: option.id,
        tableMapping: { ...option.tableMapping },
      },
    }));
  },
  setDeepSeekEnabled(enabled) {
    store.setState((state) => ({
      draft: {
        ...state.draft,
        deepseek: {
          ...state.draft.deepseek,
          enabled: Boolean(enabled),
        },
      },
    }));
  },
  updateDeepSeekField(field, value) {
    if (!field) return;
    store.setState((state) => ({
      draft: {
        ...state.draft,
        deepseek: sanitizeDeepSeekConfig({
          ...state.draft.deepseek,
          [field]: value,
        }),
      },
    }));
  },
  replaceDeepSeekConfig(config) {
    store.setState((state) => ({
      draft: {
        ...state.draft,
        deepseek: sanitizeDeepSeekConfig(config),
      },
    }));
  },
};
