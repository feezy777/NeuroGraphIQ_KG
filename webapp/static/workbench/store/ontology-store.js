import { createStore } from "./create-store.js";

const store = createStore({
  files: [],
  activeOntologyId: "",
  parsedByFileId: {},
  selectedEntityId: "",
  loadLogs: [],
});

function isOntologyFile(file) {
  const t = String(file?.file_type || "").toLowerCase();
  return ["owl", "rdf", "ttl", "jsonld", "xml"].includes(t);
}

export const ontologyStore = {
  ...store,
  syncFromFiles(files) {
    const ontologyFiles = (files || []).filter(isOntologyFile);
    store.setState((state) => {
      const activeExists = ontologyFiles.some((item) => item.file_id === state.activeOntologyId);
      return {
        files: ontologyFiles,
        activeOntologyId: activeExists
          ? state.activeOntologyId
          : ontologyFiles.length
            ? ontologyFiles[0].file_id
            : "",
      };
    });
  },
  setParsedOntology(fileId, parsed) {
    store.setState((state) => ({
      parsedByFileId: {
        ...state.parsedByFileId,
        [fileId]: parsed,
      },
      activeOntologyId: fileId,
    }));
  },
  setActiveOntology(fileId) {
    store.setState({ activeOntologyId: fileId || "" });
  },
  selectEntity(entityId) {
    store.setState({ selectedEntityId: entityId || "" });
  },
  appendLog(message) {
    store.setState((state) => ({
      loadLogs: [...state.loadLogs, message].slice(-400),
    }));
  },
};
