import { logStore } from "../../store/log-store.js";

function toConsoleMethod(level) {
  if (level === "error") return console.error;
  if (level === "warn") return console.warn;
  return console.log;
}

function log(prefix, message, level = "info", extra = {}) {
  const entry = logStore.add(prefix, message, level, extra);
  toConsoleMethod(level)(`[${entry.prefix}] ${entry.message}`, extra);
  return entry;
}

export const workspaceLogger = {
  ui(message, extra = {}, level = "info") {
    return log("UI", message, level, extra);
  },
  ontology(message, extra = {}, level = "info") {
    return log("ONTOLOGY", message, level, extra);
  },
  import(message, extra = {}, level = "info") {
    return log("IMPORT", message, level, extra);
  },
  file(message, extra = {}, level = "info") {
    return log("FILE", message, level, extra);
  },
  check(message, extra = {}, level = "info") {
    return log("CHECK", message, level, extra);
  },
  extract(message, extra = {}, level = "info") {
    return log("EXTRACT", message, level, extra);
  },
  graph(message, extra = {}, level = "info") {
    return log("GRAPH", message, level, extra);
  },
  review(message, extra = {}, level = "info") {
    return log("REVIEW", message, level, extra);
  },
};
