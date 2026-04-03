import { createStore } from "./create-store.js";

const store = createStore({
  files: [],
  stats: {},
  activeFileId: "",
  previews: {},
  reports: {},
  extractionSelections: {},
  previewPageByFileId: {},
});

export const fileStore = {
  ...store,
  setFiles(files, stats = {}) {
    store.setState((state) => {
      const safeFiles = Array.isArray(files) ? files : [];
      const activeExists = safeFiles.some((item) => item.file_id === state.activeFileId);
      const fallbackId = safeFiles.length ? safeFiles[0].file_id : "";
      return {
        files: safeFiles,
        stats: stats || {},
        activeFileId: activeExists ? state.activeFileId : fallbackId,
        extractionSelections: safeFiles.reduce((acc, item) => {
          acc[item.file_id] = state.extractionSelections[item.file_id] ?? true;
          return acc;
        }, {}),
      };
    });
  },
  setActiveFile(fileId) {
    store.setState({ activeFileId: fileId || "" });
  },
  setPreview(fileId, preview) {
    store.setState((state) => ({
      previews: {
        ...state.previews,
        [fileId]: preview,
      },
      previewPageByFileId: {
        ...state.previewPageByFileId,
        [fileId]: Number(preview?.page || 1),
      },
    }));
  },
  setReport(fileId, reportBundle) {
    store.setState((state) => ({
      reports: {
        ...state.reports,
        [fileId]: reportBundle,
      },
    }));
  },
  setExtractionSelected(fileId, checked) {
    store.setState((state) => ({
      extractionSelections: {
        ...state.extractionSelections,
        [fileId]: Boolean(checked),
      },
    }));
  },
  removeFile(fileId) {
    const id = String(fileId || "");
    if (!id) return;
    store.setState((state) => {
      const files = (state.files || []).filter((item) => item.file_id !== id);
      const activeExists = files.some((item) => item.file_id === state.activeFileId);
      const fallbackId = files.length ? files[0].file_id : "";
      const previews = { ...state.previews };
      const reports = { ...state.reports };
      const extractionSelections = { ...state.extractionSelections };
      const previewPageByFileId = { ...state.previewPageByFileId };
      delete previews[id];
      delete reports[id];
      delete extractionSelections[id];
      delete previewPageByFileId[id];
      return {
        files,
        activeFileId: activeExists ? state.activeFileId : fallbackId,
        previews,
        reports,
        extractionSelections,
        previewPageByFileId,
      };
    });
  },
};
