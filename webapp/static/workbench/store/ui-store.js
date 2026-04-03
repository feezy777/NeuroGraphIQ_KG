import { createStore } from "./create-store.js";

const store = createStore({
  activeMainTab: "tab-overview",
  activeBottomTab: "logs",
  selectedResourceId: "",
  selectedOntologyEntityId: "",
  selectedFileId: "",
  selectedExtractionJobId: "",
  selectedGraphNodeId: "",
  selectedGraphEdgeId: "",
  inspectorMode: "none",
  themeMode: "light-workspace",
  panelCollapseState: {
    "section-project-explorer": false,
    "section-ontology-rules": false,
    "section-data-sources": false,
    "section-sessions": false,
  },
});

export const uiStore = {
  ...store,
  setActiveMainTab(tabId) {
    store.setState({ activeMainTab: tabId });
  },
  setActiveBottomTab(tabId) {
    store.setState({ activeBottomTab: tabId });
  },
  setInspector(mode, payload = {}) {
    store.setState({ inspectorMode: mode, ...payload });
  },
  setThemeMode(mode) {
    store.setState({ themeMode: mode === "dark-workspace" ? "dark-workspace" : "light-workspace" });
  },
  togglePanel(sectionId) {
    store.setState((state) => ({
      panelCollapseState: {
        ...state.panelCollapseState,
        [sectionId]: !state.panelCollapseState[sectionId],
      },
    }));
  },
};
