import { createStore } from "./create-store.js";

const STORAGE_KEY = "neurokg_workbench_settings";

function readStoredSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

const defaults = {
  language: "zh-CN",
  appearance: "light-workspace",
  extractionPreferences: {
    defaultGranularity: "coarse",
    defaultOutput: "triples",
  },
  workspacePreferences: {
    defaultMainTab: "tab-overview",
    autoScrollLogs: true,
    rememberPanelCollapse: true,
  },
};

const initial = {
  ...defaults,
  ...readStoredSettings(),
  extractionPreferences: {
    ...defaults.extractionPreferences,
    ...(readStoredSettings().extractionPreferences || {}),
  },
  workspacePreferences: {
    ...defaults.workspacePreferences,
    ...(readStoredSettings().workspacePreferences || {}),
  },
};

const store = createStore(initial);

function persist(state) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        language: state.language,
        appearance: state.appearance,
        extractionPreferences: state.extractionPreferences,
        workspacePreferences: state.workspacePreferences,
      }),
    );
  } catch {
    // ignore persistence failures
  }
}

store.subscribe((state) => {
  persist(state);
});

export const settingsStore = {
  ...store,
  setLanguage(language) {
    const safe = language === "en-US" ? "en-US" : "zh-CN";
    store.setState({ language: safe });
  },
  setAppearance(appearance) {
    const safe = appearance === "dark-workspace" ? "dark-workspace" : "light-workspace";
    store.setState({ appearance: safe });
  },
  setDefaultGranularity(granularity) {
    store.setState((state) => ({
      extractionPreferences: {
        ...state.extractionPreferences,
        defaultGranularity: granularity,
      },
    }));
  },
  setDefaultOutput(output) {
    store.setState((state) => ({
      extractionPreferences: {
        ...state.extractionPreferences,
        defaultOutput: output,
      },
    }));
  },
  setWorkspacePreference(key, value) {
    store.setState((state) => ({
      workspacePreferences: {
        ...state.workspacePreferences,
        [key]: value,
      },
    }));
  },
};
