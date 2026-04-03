import { uiStore } from "./store/ui-store.js";
import { ontologyStore } from "./store/ontology-store.js";
import { fileStore } from "./store/file-store.js";
import { extractionStore } from "./store/extraction-store.js";
import { graphStore } from "./store/graph-store.js";
import { logStore } from "./store/log-store.js";
import { settingsStore } from "./store/settings-store.js";

import { workspaceLogger } from "./lib/logger/workspace-logger.js";
import { fileImportService } from "./lib/uploads/file-import-service.js";
import { importOntologyWithAdapter } from "./lib/ontology/ontology-adapter.js";
import { createExtractionJob, runExtractionJob } from "./lib/extraction/extraction-job-service.js";
import { buildGraphFromExtraction } from "./lib/graph/graph-data-adapter.js";
import { getGranularityOption } from "./lib/extraction/granularity-config.js";
import { resolveRuntimeMode } from "./lib/extraction/extraction-mode-config.js";
import { maskSensitiveField, resolveDeepSeekModel, sanitizeDeepSeekConfig } from "./lib/extraction/deepseek-default-config.js";
import { buildOverviewCards, MOCK_SESSIONS, actionHelpTemplate } from "./mock/mock-data.js";
import { apiJson } from "./lib/api.js";
import { applyI18nToDom } from "./lib/i18n/i18n.js";
import { useI18n } from "./hooks/use-i18n.js";
import { renderSettingsPanel } from "./components/settings/settings-panel.js";
import { renderExtractionTwoRowLayout } from "./components/extraction/extraction-two-row-layout.js";
import { renderExtractionInputPanel } from "./components/extraction/extraction-input-panel.js";
import { renderExtractionTaskSummaryPanel } from "./components/extraction/extraction-task-summary-panel.js";
import { renderExtractionToolbar } from "./components/extraction/extraction-toolbar.js";
import { renderDeepSeekBottomWorkbench } from "./components/extraction/deepseek-bottom-workbench.js";

const STORAGE_KEY_SNAPSHOT = "neurokg_workbench_snapshot";
const i18n = useI18n();

const dom = {
  body: document.body,
  workspaceName: document.getElementById("workspace-name"),
  inputImportOntology: document.getElementById("input-import-ontology"),
  inputImportFiles: document.getElementById("input-import-files"),
  btnImportOntology: document.getElementById("btn-import-ontology"),
  btnImportFiles: document.getElementById("btn-import-files"),
  btnNewTask: document.getElementById("btn-new-task"),
  btnSaveWorkspace: document.getElementById("btn-save-workspace"),
  btnOpenSettings: document.getElementById("btn-open-settings"),
  btnThemeToggle: document.getElementById("btn-theme-toggle"),
  btnRefreshOntology: document.getElementById("btn-refresh-ontology"),
  btnGraphFit: document.getElementById("btn-graph-fit"),
  btnGraphReset: document.getElementById("btn-graph-reset"),
  btnCrawlerCreateJob: document.getElementById("btn-crawler-create-job"),
  btnFilePreviewPrev: document.getElementById("btn-file-preview-prev"),
  btnFilePreviewNext: document.getElementById("btn-file-preview-next"),

  mainTabButtons: Array.from(document.querySelectorAll(".main-tab")),
  viewButtons: Array.from(document.querySelectorAll(".view-btn")),
  workbenchTabs: Array.from(document.querySelectorAll(".workbench-tab")),
  bottomTabs: Array.from(document.querySelectorAll(".bottom-tab")),
  sectionToggles: Array.from(document.querySelectorAll(".section-toggle")),

  treeProject: document.getElementById("tree-project"),
  treeOntologyRules: document.getElementById("tree-ontology-rules"),
  treeDataSources: document.getElementById("tree-data-sources"),
  treeSessions: document.getElementById("tree-sessions"),

  overviewCards: document.getElementById("overview-cards"),
  overviewSelection: document.getElementById("overview-selection"),

  ontologyEntityTree: document.getElementById("ontology-entity-tree"),
  ontologyFilterInput: document.getElementById("ontology-filter-input"),
  ontologySummary: document.getElementById("ontology-summary"),
  ontologyLoadLog: document.getElementById("ontology-load-log"),

  fileTable: document.getElementById("file-table"),
  filePreviewMeta: document.getElementById("file-preview-meta"),
  filePreviewEmbedWrap: document.getElementById("file-preview-embed-wrap"),
  filePreviewEmbed: document.getElementById("file-preview-embed"),
  filePreviewTableWrap: document.getElementById("file-preview-table-wrap"),
  filePreviewTable: document.getElementById("file-preview-table"),
  filePreviewContent: document.getElementById("file-preview-content"),
  fileCheckStateLine: document.getElementById("file-check-state-line"),
  fileCheckFileLine: document.getElementById("file-check-file-line"),
  fileCheckDeepseekLine: document.getElementById("file-check-deepseek-line"),
  fileCheckResultLine: document.getElementById("file-check-result-line"),
  fileCheckLog: document.getElementById("file-check-log"),

  extractOntologySelect: document.getElementById("extract-ontology-select"),
  extractTargetsWrap: document.getElementById("extract-targets"),
  extractFileList: document.getElementById("extract-file-list"),
  extractionJobTable: document.getElementById("extraction-job-table"),
  extractionWorkbenchRoot: document.getElementById("extraction-workbench-root"),
  extractionInputPanel: document.getElementById("extraction-input-panel"),
  extractionTaskSummaryPanel: document.getElementById("extraction-task-summary-panel"),
  deepseekBottomWorkbenchPanel: document.getElementById("deepseek-bottom-workbench-panel"),
  extractionToolbarHost: document.getElementById("extraction-toolbar-host"),
  deepseekWorkbenchHost: document.getElementById("deepseek-workbench-host"),

  graphFilterType: document.getElementById("graph-filter-type"),
  graphCanvas: document.getElementById("graph-canvas"),
  graphNodeTable: document.getElementById("graph-node-table"),
  graphEdgeTable: document.getElementById("graph-edge-table"),

  reviewEntityTable: document.getElementById("review-entity-table"),
  reviewRelationTable: document.getElementById("review-relation-table"),
  reviewCircuitTable: document.getElementById("review-circuit-table"),

  crawlerSourceType: document.getElementById("crawler-source-type"),
  crawlerSourceInput: document.getElementById("crawler-source-input"),
  crawlerStatus: document.getElementById("crawler-status"),

  settingsPanelHost: document.getElementById("settings-panel-host"),
  mainConsoleLog: document.getElementById("main-console-log"),
  inspectorMode: document.getElementById("inspector-mode"),
  inspectorContent: document.getElementById("inspector-content"),
  inspectorActionHelp: document.getElementById("inspector-action-help"),

  bottomViews: {
    logs: document.getElementById("bottom-logs"),
    tasks: document.getElementById("bottom-tasks"),
    problems: document.getElementById("bottom-problems"),
    trace: document.getElementById("bottom-trace"),
  },
};

const localState = {
  runtimeStatus: null,
  actionId: "import_ontology",
  crawlerLastStatus: "",
  extractionLayoutMode: "",
  ontologyFilterKeyword: "",
  ontologyGroupCollapsed: {},
  sidebarOntologyGroupCollapsed: {},
  validationTraceByFileId: {},
};

let renderQueued = false;
let restoringSnapshot = false;

const t = (key) => i18n.t(key);
const lang = () => settingsStore.getState().language || "zh-CN";

function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pretty(v) {
  if (typeof v === "string") return v;
  return JSON.stringify(v ?? {}, null, 2);
}

function bytes(v) {
  const n = Number(v || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function timeText(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(lang() === "en-US" ? "en-US" : "zh-CN");
}

function granularityLabel(id) {
  const opt = getGranularityOption(id);
  return lang() === "en-US" ? opt.labelEn : opt.labelZh;
}

function runtimeModeLabel(runtimeMode) {
  return runtimeMode === "deepseek" ? t("extraction.deepseek.modeDeepseek") : t("extraction.deepseek.modePlaceholder");
}

function setActionHelp(actionId) {
  localState.actionId = actionId;
  renderInspectorPanel();
}

function setMainTab(tabId) {
  uiStore.setActiveMainTab(tabId);
}

function setBottomTab(tabId) {
  uiStore.setActiveBottomTab(tabId);
}

function applyTheme(theme, reason = "init") {
  const safe = theme === "dark-workspace" ? "dark-workspace" : "light-workspace";
  settingsStore.setAppearance(safe);
  uiStore.setThemeMode(safe);
  dom.body.setAttribute("data-theme", safe);
  workspaceLogger.ui(`[THEME] apply theme=${safe} reason=${reason}`);
}

function applyLanguage(language, reason = "manual") {
  const prev = settingsStore.getState().language;
  settingsStore.setLanguage(language);
  const next = settingsStore.getState().language;
  document.documentElement.lang = next === "en-US" ? "en" : "zh-CN";
  applyI18nToDom(t);
  document.title = t("app.title");
  dom.workspaceName.textContent = `${next === "en-US" ? "workspace" : "工作区"}: NeuroGraphIQ_KG_V2`;
  if (prev !== next) workspaceLogger.ui(`[I18N] language_change from=${prev} to=${next} reason=${reason}`);
}

function selectFile(fileId) {
  const id = fileId || "";
  fileStore.setActiveFile(id);
  uiStore.setState({ selectedFileId: id, selectedResourceId: id, inspectorMode: id ? "file" : "none" });
}

function selectOntologyEntity(entityId) {
  const id = entityId || "";
  ontologyStore.selectEntity(id);
  uiStore.setState({ selectedOntologyEntityId: id, selectedResourceId: id, inspectorMode: id ? "ontology_entity" : "none" });
  if (id) {
    const entity = flattenOntology(activeParsedOntology()).find((item) => item.id === id);
    workspaceLogger.ontology(`[TREE] select iri=${entity?.iri || id}`);
  }
}

function selectExtractionJob(jobId) {
  const id = jobId || "";
  extractionStore.setActiveJob(id);
  uiStore.setState({ selectedExtractionJobId: id, selectedResourceId: id, inspectorMode: id ? "extraction_job" : "none" });
}

function selectGraphNode(id) {
  uiStore.setState({ selectedGraphNodeId: id || "", selectedGraphEdgeId: "", selectedResourceId: id || "", inspectorMode: id ? "graph_node" : "none" });
}

function selectGraphEdge(id) {
  uiStore.setState({ selectedGraphNodeId: "", selectedGraphEdgeId: id || "", selectedResourceId: id || "", inspectorMode: id ? "graph_edge" : "none" });
}

function activeOntologyFile() {
  const s = ontologyStore.getState();
  return s.files.find((x) => x.file_id === s.activeOntologyId) || null;
}

function activeParsedOntology() {
  const s = ontologyStore.getState();
  return s.parsedByFileId[s.activeOntologyId] || null;
}

function selectedFile() {
  const s = fileStore.getState();
  return s.files.find((x) => x.file_id === s.activeFileId) || null;
}

function activeJob() {
  const s = extractionStore.getState();
  return s.jobs.find((x) => x.id === s.activeJobId) || null;
}

function flattenOntology(parsed) {
  if (!parsed?.entities) return [];
  const groups = [
    { key: "classes", type: "class" },
    { key: "objectProperties", type: "object_property" },
    { key: "dataProperties", type: "data_property" },
    { key: "individuals", type: "individual" },
    { key: "constraints", type: "constraint" },
  ];
  const out = [];
  groups.forEach((g) => (parsed.entities[g.key] || []).forEach((e) => out.push({ ...e, __type: g.type, __group: g.key })));
  return out;
}

function normalizeKeyword(value) {
  return String(value || "").trim().toLowerCase();
}

function filterOntologyItems(items, keyword) {
  const key = normalizeKeyword(keyword);
  if (!key) return items;
  return (items || []).filter((item) => {
    const label = String(item?.label || "").toLowerCase();
    const iri = String(item?.iri || "").toLowerCase();
    const id = String(item?.id || "").toLowerCase();
    return label.includes(key) || iri.includes(key) || id.includes(key);
  });
}

function extractionTargets() {
  return Array.from(dom.extractTargetsWrap.querySelectorAll("input[type='checkbox']")).filter((n) => n.checked).map((n) => n.value);
}

function extractionFiles() {
  const s = fileStore.getState();
  return s.files.filter((f) => s.extractionSelections[f.file_id]);
}

function renderTable(table, rows, cols, opts = {}) {
  if (!table) return;
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    table.innerHTML = `<thead><tr><th>${esc(t("common.info"))}</th></tr></thead><tbody><tr><td>${esc(opts.emptyText || t("common.noData"))}</td></tr></tbody>`;
    return;
  }
  const head = `<thead><tr>${cols.map((c) => `<th>${esc(c.label || c.key)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${list
    .map((row) => {
      const rowId = opts.rowId ? String(row[opts.rowId] || "") : "";
      const active = rowId && opts.activeRowId === rowId ? " class=\"active-row\"" : "";
      const rowAttr = rowId ? ` data-row-id="${esc(rowId)}"` : "";
      const cells = cols
        .map((c) => {
          const value = typeof c.render === "function" ? c.render(row, row[c.key]) : row[c.key];
          if (c.raw) {
            return `<td>${value === undefined || value === null || value === "" ? "-" : String(value)}</td>`;
          }
          return `<td>${esc(value === undefined || value === null || value === "" ? "-" : value)}</td>`;
        })
        .join("");
      return `<tr${active}${rowAttr}>${cells}</tr>`;
    })
    .join("")}</tbody>`;
  table.innerHTML = head + body;
  if (opts.rowId && typeof opts.onRowClick === "function") {
    table.querySelectorAll("tbody tr[data-row-id]").forEach((node) =>
      node.addEventListener("click", (event) => {
        const target = event.target;
        if (target instanceof Element && target.closest("[data-stop-row-click='1']")) return;
        opts.onRowClick(node.getAttribute("data-row-id") || "");
      }));
  }
  if (typeof opts.afterRender === "function") opts.afterRender(table);
}

function saveSnapshot() {
  const payload = { ui: uiStore.getState(), actionId: localState.actionId };
  try {
    localStorage.setItem(STORAGE_KEY_SNAPSHOT, JSON.stringify(payload));
    workspaceLogger.ui("workspace_snapshot_saved");
  } catch (e) {
    workspaceLogger.ui(`workspace_snapshot_save_failed error=${String(e)}`, {}, "warn");
  }
}

function restoreSnapshot() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_SNAPSHOT);
    if (!raw) return;
    const data = JSON.parse(raw);
    restoringSnapshot = true;
    if (data?.ui?.activeMainTab) uiStore.setActiveMainTab(data.ui.activeMainTab);
    if (data?.ui?.activeBottomTab) uiStore.setActiveBottomTab(data.ui.activeBottomTab);
    if (data?.ui?.panelCollapseState) uiStore.setState({ panelCollapseState: data.ui.panelCollapseState });
    if (data?.actionId) localState.actionId = data.actionId;
    restoringSnapshot = false;
    workspaceLogger.ui("workspace_snapshot_restored");
  } catch (e) {
    restoringSnapshot = false;
    workspaceLogger.ui(`workspace_snapshot_restore_failed error=${String(e)}`, {}, "warn");
  }
}

async function loadRuntimeStatus() {
  try {
    localState.runtimeStatus = await apiJson("/api/status");
    workspaceLogger.ui(`status_loaded db_connected=${Boolean(localState.runtimeStatus?.database?.connected)}`);
  } catch (e) {
    workspaceLogger.ui(`status_load_failed error=${String(e)}`, {}, "warn");
  }
}

async function ensureOntologyParsed(fileId) {
  const s = ontologyStore.getState();
  if (!fileId || s.parsedByFileId[fileId]) return;
  const file = s.files.find((x) => x.file_id === fileId);
  if (!file) return;
  try {
    const result = await importOntologyWithAdapter(file, fileImportService);
    ontologyStore.setParsedOntology(fileId, result.parsed);
    (result.logs || []).forEach((line) => {
      ontologyStore.appendLog(line);
      workspaceLogger.ontology(line);
    });
  } catch (e) {
    const msg = `[ONTOLOGY] import_failed file=${file.filename} error=${String(e)}`;
    ontologyStore.appendLog(msg);
    workspaceLogger.ontology(msg, {}, "error");
  }
}

async function refreshFilesAndOntology({ parseOntologies = false } = {}) {
  const result = await fileImportService.listFiles();
  fileStore.setFiles(result?.files || [], result?.stats || {});
  ontologyStore.syncFromFiles(fileStore.getState().files);
  if (parseOntologies) {
    for (const file of ontologyStore.getState().files) await ensureOntologyParsed(file.file_id);
  } else if (ontologyStore.getState().activeOntologyId) {
    await ensureOntologyParsed(ontologyStore.getState().activeOntologyId);
  }
  workspaceLogger.import(`file_list_refresh total=${result?.stats?.total || 0} validated=${result?.stats?.validated || 0}`);
}

async function loadFilePreview(fileId, page = 1) {
  if (!fileId) return;
  try {
    const preview = await fileImportService.getPreview(fileId, { page, pageSize: 120, view: "auto" });
    fileStore.setPreview(fileId, preview);
  } catch (e) {
    workspaceLogger.import(`file_preview_failed file_id=${fileId} error=${String(e)}`, {}, "error");
  }
}

async function loadFileReport(fileId) {
  if (!fileId) return;
  try {
    const bundle = await fileImportService.getReport(fileId);
    fileStore.setReport(fileId, bundle);
    applyValidationTraceFromReport(fileId, bundle?.report || {}, { emitLogs: false });
  } catch (e) {
    workspaceLogger.file(`[REPORT] failed file_id=${fileId} error=${String(e)}`, {}, "warn");
  }
}

function ensureValidationTrace(fileId) {
  const id = String(fileId || "").trim();
  if (!id) return null;
  if (!localState.validationTraceByFileId[id]) {
    localState.validationTraceByFileId[id] = {
      status: "idle",
      fileId: id,
      deepseekCalled: false,
      result: "UNKNOWN",
      logs: [],
    };
  }
  return localState.validationTraceByFileId[id];
}

function setValidationTraceStatus(fileId, status) {
  const trace = ensureValidationTrace(fileId);
  if (!trace) return;
  trace.status = String(status || "idle");
  scheduleRender();
}

function buildTaskDeepSeekOverride() {
  const draft = extractionStore.getState().draft || {};
  const safe = sanitizeDeepSeekConfig(draft.deepseek || {});
  if (!safe.useTaskOverride) return null;
  return {
    enabled: Boolean(safe.enabled),
    deepseek: {
      api_key: String(safe.apiKey || "").trim(),
      base_url: String(safe.baseUrl || "").trim(),
      model: String(resolveDeepSeekModel(safe) || "").trim(),
    },
  };
}

function resetValidationTrace(fileId) {
  const trace = ensureValidationTrace(fileId);
  if (!trace) return;
  trace.status = "idle";
  trace.deepseekCalled = false;
  trace.result = "UNKNOWN";
  trace.logs = [];
  scheduleRender();
}

function appendCheckLog(fileId, message, level = "info") {
  const trace = ensureValidationTrace(fileId);
  if (!trace) return;
  const text = String(message || "");
  const stamp = new Date().toISOString();
  trace.logs.push(`[${stamp}] ${text}`);
  if (trace.logs.length > 240) trace.logs = trace.logs.slice(-240);
  workspaceLogger.check(text, { file_id: String(fileId || "") }, level);
  scheduleRender();
}

function applyValidationTraceFromReport(fileId, report, { emitLogs = false } = {}) {
  const trace = ensureValidationTrace(fileId);
  if (!trace || !report || typeof report !== "object") return;
  const llm = report?.validation_trace?.llm_initial || {};
  const requestSent = Boolean(llm?.request_sent);
  const responseReceived = Boolean(llm?.response_received);
  trace.fileId = String(fileId || "");
  trace.deepseekCalled = requestSent && responseReceived;
  trace.result = String(report?.overall_label || "UNKNOWN");
  trace.status = trace.result && trace.result !== "UNKNOWN" ? "success" : "failed";
  if (!emitLogs) return;

  appendCheckLog(fileId, `start file_id=${trace.fileId}`);
  appendCheckLog(fileId, "calling deepseek");
  if (requestSent) {
    appendCheckLog(fileId, `request -> ${llm?.request_target || "deepseek.com"}`);
  } else {
    appendCheckLog(fileId, "request -> deepseek (not_sent)", "warn");
  }
  if (responseReceived) {
    appendCheckLog(fileId, `response status=${llm?.http_status ?? 200}`);
  } else {
    appendCheckLog(fileId, "response status=NA", "warn");
  }
  appendCheckLog(fileId, `success verdict=${trace.result}`);
}

function checkStatusLabel(status) {
  if (status === "running") return t("files.check.statusRunning");
  if (status === "success") return t("files.check.statusSuccess");
  if (status === "failed") return t("files.check.statusFailed");
  return t("files.check.statusIdle");
}

function renderValidationCheckPanel() {
  if (!dom.fileCheckStateLine || !dom.fileCheckFileLine || !dom.fileCheckDeepseekLine || !dom.fileCheckResultLine || !dom.fileCheckLog) {
    return;
  }
  const file = selectedFile();
  if (!file) {
    dom.fileCheckStateLine.textContent = `${t("files.check.state")}: ${t("files.check.statusIdle")}`;
    dom.fileCheckFileLine.textContent = `${t("files.check.fileId")}: -`;
    dom.fileCheckDeepseekLine.textContent = `${t("files.check.deepseekCalled")}: -`;
    dom.fileCheckResultLine.textContent = `${t("files.check.result")}: -`;
    dom.fileCheckLog.textContent = t("files.check.noLogs");
    return;
  }

  const report = fileStore.getState().reports[file.file_id]?.report || null;
  if (report && !localState.validationTraceByFileId[file.file_id]) {
    applyValidationTraceFromReport(file.file_id, report, { emitLogs: false });
  }
  const trace = ensureValidationTrace(file.file_id);
  const stateFromFileStatus =
    file.status === "validating" ? "running" : file.status === "validation_failed" ? "failed" : file.status === "validated" || file.status === "processed" ? "success" : "idle";
  const finalStatus = trace?.status && trace.status !== "idle" ? trace.status : stateFromFileStatus;
  const deepseekCalled = trace?.deepseekCalled ? t("files.check.calledYes") : t("files.check.calledNo");
  const result = trace?.result || report?.overall_label || file?.overall_label || "UNKNOWN";
  const logs = trace?.logs || [];

  dom.fileCheckStateLine.textContent = `${t("files.check.state")}: ${checkStatusLabel(finalStatus)}`;
  dom.fileCheckFileLine.textContent = `${t("files.check.fileId")}: ${file.file_id}`;
  dom.fileCheckDeepseekLine.textContent = `${t("files.check.deepseekCalled")}: ${deepseekCalled}`;
  dom.fileCheckResultLine.textContent = `${t("files.check.result")}: ${result}`;
  dom.fileCheckLog.textContent = logs.length ? logs.join("\n") : t("files.check.noLogs");
}

async function validateAndPrepareFile(fileId) {
  const deepseekOverride = buildTaskDeepSeekOverride();
  const source = deepseekOverride ? "override" : "global";
  resetValidationTrace(fileId);
  setValidationTraceStatus(fileId, "running");
  appendCheckLog(fileId, `start file_id=${fileId}`);
  appendCheckLog(fileId, `deepseek config source=${source}`);
  if (deepseekOverride?.deepseek) {
    appendCheckLog(
      fileId,
      `model=${deepseekOverride.deepseek.model || "-"} baseUrl=${deepseekOverride.deepseek.base_url || "-"}`,
    );
  }
  appendCheckLog(fileId, "calling deepseek");
  workspaceLogger.file(`[VALIDATE] queued file_id=${fileId}`);
  fileStore.setFiles(
    fileStore.getState().files.map((item) => (item.file_id === fileId ? { ...item, status: "validating" } : item)),
    fileStore.getState().stats,
  );
  try {
    workspaceLogger.file(`[VALIDATE] start file_id=${fileId}`);
    const validated = await fileImportService.validateFile(fileId, {
      deepseekOverride: deepseekOverride || undefined,
    });
    const report = validated?.validation_report || {};
    const cfg = validated?.deepseek_config || {};
    const trace = report?.validation_trace?.llm_initial || {};
    appendCheckLog(
      fileId,
      `deepseek config source=${cfg?.source || source} model=${cfg?.model || "-"} baseUrl=${cfg?.base_url || "-"}`,
    );
    if (trace?.request_sent) {
      appendCheckLog(fileId, `request -> ${trace?.request_target || "deepseek.com"}`);
    } else {
      appendCheckLog(fileId, "request -> deepseek (not_sent)", "warn");
    }
    if (trace?.response_received) {
      appendCheckLog(fileId, `response status=${trace?.http_status ?? 200}`);
    } else {
      appendCheckLog(fileId, "response status=NA", "warn");
    }
    applyValidationTraceFromReport(fileId, report, { emitLogs: false });
    setValidationTraceStatus(fileId, "success");
    appendCheckLog(fileId, `success file_id=${fileId} verdict=${report?.overall_label || "UNKNOWN"}`);
    workspaceLogger.file(
      `[VALIDATE][DEEPSEEK] request file_id=${fileId} model=${String(localState.runtimeStatus?.config?.deepseek?.model || "deepseek-chat")}`,
    );
    workspaceLogger.file(
      `[VALIDATE][DEEPSEEK] response file_id=${fileId} verdict=${report?.overall_label || "UNKNOWN"} effective=${trace?.effective_use_deepseek ? 1 : 0}`,
    );
    workspaceLogger.file(`[VALIDATE] finish file_id=${fileId} verdict=${report?.overall_label || "UNKNOWN"} confidence=${report?.score ?? "-"}`);
    await loadFileReport(fileId);
  } catch (e) {
    setValidationTraceStatus(fileId, "failed");
    appendCheckLog(fileId, `failed file_id=${fileId} reason=${String(e)}`, "error");
    workspaceLogger.file(`[VALIDATE] failed file_id=${fileId} reason=${String(e)}`, {}, "warn");
  }
}

async function handleImportFiles(files, sourceType) {
  if (!files.length) return;
  setActionHelp(sourceType === "ontology" ? "import_ontology" : "import_files");
  const uploaded = await fileImportService.uploadFiles(files);
  uploaded.forEach((f) => workspaceLogger.file(`upload_success file=${f.filename} type=${f.file_type}`));
  await refreshFilesAndOntology({ parseOntologies: false });

  for (const file of uploaded) {
    const isOntology = ["owl", "rdf", "ttl", "jsonld", "xml"].includes(String(file.file_type || "").toLowerCase());
    if (isOntology) {
      await ensureOntologyParsed(file.file_id);
      continue;
    }
    const autoValidation = file.__upload_meta?.auto_validation || {};
    if (autoValidation?.triggered && autoValidation?.status === "ok") {
      resetValidationTrace(file.file_id);
      setValidationTraceStatus(file.file_id, "running");
      appendCheckLog(file.file_id, `start file_id=${file.file_id}`);
      appendCheckLog(file.file_id, `deepseek config source=${autoValidation?.source || "global"}`);
      appendCheckLog(file.file_id, "calling deepseek");
      workspaceLogger.file(`[VALIDATE] queued file_id=${file.file_id}`);
      workspaceLogger.file(`[VALIDATE] start file_id=${file.file_id}`);
      if (autoValidation?.request_sent) {
        appendCheckLog(file.file_id, "request -> deepseek.com");
      } else {
        appendCheckLog(file.file_id, "request -> deepseek (not_sent)", "warn");
      }
      if (autoValidation?.response_received) {
        appendCheckLog(file.file_id, `response status=${autoValidation?.http_status ?? 200}`);
      } else {
        appendCheckLog(file.file_id, "response status=NA", "warn");
      }
      workspaceLogger.file(
        `[VALIDATE] finish file_id=${file.file_id} verdict=${autoValidation?.label || "UNKNOWN"} confidence=${autoValidation?.score ?? "-"}`,
      );
      workspaceLogger.file(
        `[VALIDATE][DEEPSEEK] response file_id=${file.file_id} verdict=${autoValidation?.label || "UNKNOWN"} effective=${autoValidation?.effective_use_deepseek ? 1 : 0}`,
      );
      await loadFileReport(file.file_id);
      const report = fileStore.getState().reports[file.file_id]?.report || null;
      if (report) {
        applyValidationTraceFromReport(file.file_id, report, { emitLogs: false });
      } else {
        const trace = ensureValidationTrace(file.file_id);
        if (trace) {
          trace.result = String(autoValidation?.label || "UNKNOWN");
          trace.deepseekCalled = Boolean(autoValidation?.request_sent && autoValidation?.response_received);
          trace.status = "success";
        }
      }
      setValidationTraceStatus(file.file_id, "success");
      appendCheckLog(file.file_id, `success file_id=${file.file_id} verdict=${autoValidation?.label || "UNKNOWN"}`);
    } else {
      if (autoValidation?.triggered && autoValidation?.status === "error") {
        workspaceLogger.file(`[VALIDATE] auto_failed file_id=${file.file_id} reason=${autoValidation?.reason || "unknown"}`, {}, "warn");
        resetValidationTrace(file.file_id);
        setValidationTraceStatus(file.file_id, "failed");
        appendCheckLog(file.file_id, `failed file_id=${file.file_id} reason=${autoValidation?.reason || "unknown"}`, "error");
      }
      await validateAndPrepareFile(file.file_id);
    }
  }

  await refreshFilesAndOntology({ parseOntologies: false });
  if (uploaded[0]?.file_id) {
    selectFile(uploaded[0].file_id);
    await loadFilePreview(uploaded[0].file_id, 1);
    await loadFileReport(uploaded[0].file_id);
  }
  setMainTab(sourceType === "ontology" ? "tab-ontology" : "tab-files");
}

async function removeFile(fileId) {
  const current = fileStore.getState().files.find((x) => x.file_id === fileId);
  if (!current) return;
  const confirmed = window.confirm(
    `${t("files.removeConfirm")}\n${current.filename}`,
  );
  if (!confirmed) return;

  workspaceLogger.file(`[REMOVE] start file_id=${fileId}`);
  try {
    const removed = await fileImportService.removeFile(fileId);
    if (!removed?.removed?.removed && !removed?.removed && !removed?.success) {
      workspaceLogger.file(`[REMOVE] failed file_id=${fileId} reason=unexpected_response`, {}, "error");
      return;
    }

    fileStore.removeFile(fileId);
    const selected = uiStore.getState().selectedFileId;
    if (selected === fileId) {
      const nextId = fileStore.getState().activeFileId || "";
      uiStore.setState({ selectedFileId: nextId, selectedResourceId: nextId, inspectorMode: nextId ? "file" : "none" });
    }

    await refreshFilesAndOntology({ parseOntologies: false });
    const activeId = fileStore.getState().activeFileId;
    if (activeId) {
      await loadFilePreview(activeId, fileStore.getState().previewPageByFileId[activeId] || 1);
      await loadFileReport(activeId);
    } else {
      uiStore.setState({ selectedFileId: "", inspectorMode: "none", selectedResourceId: "" });
    }
    workspaceLogger.file(`[REMOVE] success file_id=${fileId} name=${current.filename}`);
  } catch (e) {
    workspaceLogger.file(`[REMOVE] failed file_id=${fileId} reason=${String(e)}`, {}, "error");
  }
}

function changeGranularity(next, reason = "manual") {
  const prev = extractionStore.getState().draft.granularity;
  if (prev === next) return;
  extractionStore.setGranularity(next);
  const m = extractionStore.getState().draft.tableMapping;
  workspaceLogger.extract(`[GRANULARITY] change from=${prev} to=${next} reason=${reason}`);
  workspaceLogger.extract(`[TABLE_MAP] granularity=${next} entity=${m.entityTable} relation=${m.relationTable} circuit=${m.circuitTable}`);
}

function toggleDeepSeek(enabled) {
  extractionStore.setDeepSeekEnabled(enabled);
  workspaceLogger.extract(`[DEEPSEEK] toggle enabled=${enabled ? 1 : 0}`);
}

function updateDeepSeekField(field, value) {
  extractionStore.updateDeepSeekField(field, value);
  const masked = maskSensitiveField(field, value);
  workspaceLogger.extract(`[DEEPSEEK] config_update field=${field} value=${masked}`);
}

async function startExtractionJob() {
  setActionHelp("start_extraction");
  const ontologyId = String(dom.extractOntologySelect.value || "").trim();
  const files = extractionFiles();
  const targets = extractionTargets();
  const draft = extractionStore.getState().draft;
  const deepseekConfig = sanitizeDeepSeekConfig(draft.deepseek || {});
  const deepseekSource = deepseekConfig.useTaskOverride ? "override" : "global";
  const runtimeMode = resolveRuntimeMode(deepseekConfig.enabled);

  if (!ontologyId) {
    workspaceLogger.extract("job_blocked reason=ontology_missing", {}, "error");
    uiStore.setState({ inspectorMode: "warning" });
    return;
  }
  if (!files.length) {
    workspaceLogger.extract("job_blocked reason=input_files_missing", {}, "error");
    uiStore.setState({ inspectorMode: "warning" });
    return;
  }

  const job = createExtractionJob({
    ontologyId,
    fileIds: files.map((f) => f.file_id),
    targets,
    mode: draft.mode,
    output: draft.output,
    granularity: draft.granularity,
    tableMapping: draft.tableMapping,
    deepseekConfig,
  });

  extractionStore.addJob(job);
  uiStore.setState({ selectedExtractionJobId: job.id, inspectorMode: "extraction_job" });
  if (runtimeMode === "deepseek") {
    workspaceLogger.extract(
      `job_create id=${job.id} mode=deepseek source=${deepseekSource} model=${resolveDeepSeekModel(deepseekConfig)} temperature=${deepseekConfig.temperature} granularity=${job.granularity} entity_table=${job.tableMapping.entityTable}`,
    );
  } else {
    workspaceLogger.extract(`job_create id=${job.id} mode=placeholder granularity=${job.granularity} entity_table=${job.tableMapping.entityTable}`);
  }

  const context = { ontology: ontologyStore.getState().files.find((x) => x.file_id === ontologyId) || null, files };
  try {
    await runExtractionJob(job, context, {
      onProgress(nextJob) {
        extractionStore.updateJob(job.id, nextJob);
        workspaceLogger.extract(`job_progress id=${job.id} stage=${nextJob.stage} progress=${nextJob.progress}`);
      },
      onComplete(done, result) {
        extractionStore.updateJob(job.id, done);
        extractionStore.setJobResult(job.id, result);
        const graph = buildGraphFromExtraction(result);
        graphStore.setGraphData({ nodes: graph.nodes, edges: graph.edges });
        graphStore.setReviewData(graph.review);
        workspaceLogger.extract(`job_finish id=${job.id} entities=${result.summary.entities} relations=${result.summary.relations} circuits=${result.summary.circuits}`);
      },
      onError(failed, err) {
        extractionStore.updateJob(job.id, failed);
        workspaceLogger.extract(`job_fail id=${job.id} error=${String(err)}`, {}, "error");
      },
    });
  } catch {
    // already logged
  }
}
function renderSidebarProjectExplorer() {
  const nodes = [
    { group: "ontology/", value: ontologyStore.getState().files.length, tab: "tab-ontology" },
    { group: "uploads/", value: fileStore.getState().files.length, tab: "tab-files" },
    { group: "extraction_jobs/", value: extractionStore.getState().jobs.length, tab: "tab-extraction" },
    { group: "graph_views/", value: graphStore.getState().nodes.length, tab: "tab-graph" },
    { group: "logs/", value: logStore.getState().items.length, tab: "tab-console" },
  ];
  dom.treeProject.innerHTML = nodes
    .map((item) => `<li class="tree-item ${uiStore.getState().activeMainTab === item.tab ? "active" : ""}" data-open-tab="${esc(item.tab)}">${esc(item.group)} <span class="meta-text">(${item.value})</span></li>`)
    .join("");
  dom.treeProject.querySelectorAll("[data-open-tab]").forEach((node) => node.addEventListener("click", () => setMainTab(node.getAttribute("data-open-tab") || "tab-overview")));
}

function renderSidebarOntologyRules() {
  const parsed = activeParsedOntology();
  if (!parsed) {
    dom.treeOntologyRules.innerHTML = `<li class="tree-item">${esc(t("common.noOntology"))}</li>`;
    return;
  }
  const groups = [
    { key: "classes", label: "Classes", list: parsed.entities?.classes || [] },
    { key: "objectProperties", label: "Object Properties", list: parsed.entities?.objectProperties || [] },
    { key: "dataProperties", label: "Data Properties", list: parsed.entities?.dataProperties || [] },
    { key: "individuals", label: "Individuals", list: parsed.entities?.individuals || [] },
    { key: "constraints", label: "Constraints", list: parsed.entities?.constraints || [] },
  ];
  const keyword = localState.ontologyFilterKeyword;
  dom.treeOntologyRules.innerHTML = groups
    .map((g) => {
      const filtered = filterOntologyItems(g.list, keyword);
      const collapsed = Boolean(localState.sidebarOntologyGroupCollapsed[g.key]);
      const children = filtered
        .map((item) => `<li class="tree-item ${ontologyStore.getState().selectedEntityId === item.id ? "active" : ""}" data-entity-id="${esc(item.id)}">${esc(item.label || item.id)}</li>`)
        .join("");
      const title = `${g.label} (${filtered.length}/${g.list.length})`;
      if (collapsed) {
        return `<li class="tree-group-label"><button type="button" class="tree-group-toggle" data-sidebar-ontology-group="${esc(g.key)}">${esc(title)}</button></li>`;
      }
      return `<li class="tree-group-label"><button type="button" class="tree-group-toggle" data-sidebar-ontology-group="${esc(g.key)}">${esc(title)}</button></li>${children || `<li class="tree-item tree-item-muted">${esc(t("common.noData"))}</li>`}`;
    })
    .join("");
  dom.treeOntologyRules.querySelectorAll("[data-sidebar-ontology-group]").forEach((node) => {
    node.addEventListener("click", () => {
      const key = String(node.getAttribute("data-sidebar-ontology-group") || "");
      localState.sidebarOntologyGroupCollapsed[key] = !Boolean(localState.sidebarOntologyGroupCollapsed[key]);
      scheduleRender();
    });
  });
  dom.treeOntologyRules.querySelectorAll("[data-entity-id]").forEach((node) => {
    node.addEventListener("click", () => {
      selectOntologyEntity(node.getAttribute("data-entity-id") || "");
      setMainTab("tab-ontology");
    });
  });
}

function renderSidebarDataSources() {
  const files = fileStore.getState().files;
  if (!files.length) {
    dom.treeDataSources.innerHTML = `<li class="tree-item">${esc(t("common.noFile"))}</li>`;
    return;
  }
  dom.treeDataSources.innerHTML = files
    .map((file) => `<li class="tree-item ${file.file_id === fileStore.getState().activeFileId ? "active" : ""}" data-file-id="${esc(file.file_id)}">${esc(file.filename)} <span class="meta-text">[${esc(file.overall_label || "UNPROCESSED")}]</span></li>`)
    .join("");
  dom.treeDataSources.querySelectorAll("[data-file-id]").forEach((node) => {
    node.addEventListener("click", async () => {
      const id = node.getAttribute("data-file-id") || "";
      selectFile(id);
      setMainTab("tab-files");
      await loadFilePreview(id, fileStore.getState().previewPageByFileId[id] || 1);
      await loadFileReport(id);
    });
  });
}

function renderSidebarSessions() {
  dom.treeSessions.innerHTML = MOCK_SESSIONS.map((s) => `<li class="tree-item">${esc(s.label)}</li>`).join("");
}

function renderOverview() {
  const cards = buildOverviewCards({
    ontologyCount: ontologyStore.getState().files.length,
    fileCount: fileStore.getState().files.length,
    jobCount: extractionStore.getState().jobs.length,
    entityCount: graphStore.getState().review.entities.length,
    relationCount: graphStore.getState().review.relations.length,
    circuitCount: graphStore.getState().review.circuits.length,
  });
  dom.overviewCards.innerHTML = cards.map((c) => `<div class="overview-card"><div class="title">${esc(c.label)}</div><div class="value">${esc(c.value)}</div></div>`).join("");
  const ui = uiStore.getState();
  dom.overviewSelection.textContent = ui.selectedResourceId
    ? `${t("inspector.modeLabel")}: ${ui.inspectorMode}\n${t("inspector.resourceId")}: ${ui.selectedResourceId}\n${t("app.tabsLabel")}: ${ui.activeMainTab}`
    : t("common.noneSelected");
}

function renderKV(target, rows) {
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = `<div class="kv-key">${esc(t("common.info"))}</div><div class="kv-value">${esc(t("common.noData"))}</div>`;
    return;
  }
  target.innerHTML = rows.map((r) => `<div class="kv-key">${esc(r.key)}</div><div class="kv-value${r.mono ? " mono" : ""}">${esc(r.value ?? "-")}</div>`).join("");
}

function renderOntologyWorkspace() {
  const file = activeOntologyFile();
  const parsed = activeParsedOntology();
  const keyword = localState.ontologyFilterKeyword;
  if (dom.ontologyFilterInput) {
    dom.ontologyFilterInput.placeholder = t("ontology.searchPlaceholder");
    dom.ontologyFilterInput.value = keyword;
  }

  if (!parsed) {
    dom.ontologyEntityTree.innerHTML = `<li class="tree-item">${esc(t("common.noOntology"))}</li>`;
    renderKV(dom.ontologySummary, [
      { key: t("inspector.fields.name"), value: file?.filename || "-" },
      { key: t("inspector.fields.status"), value: t("common.waitingImport") },
    ]);
  } else {
    const groups = [
      { key: "classes", label: "Classes" },
      { key: "objectProperties", label: "Object Properties" },
      { key: "dataProperties", label: "Data Properties" },
      { key: "individuals", label: "Individuals" },
      { key: "constraints", label: "Constraints" },
    ];
    dom.ontologyEntityTree.innerHTML = groups
      .map((g) => {
        const list = parsed.entities?.[g.key] || [];
        const filtered = filterOntologyItems(list, keyword);
        const collapsed = Boolean(localState.ontologyGroupCollapsed[g.key]);
        const items = filtered
          .map((item) => `<li class="tree-item ${ontologyStore.getState().selectedEntityId === item.id ? "active" : ""}" data-entity-id="${esc(item.id)}">${esc(item.label || item.id)}</li>`)
          .join("");
        const title = `${g.label} (${filtered.length}/${list.length})`;
        if (collapsed) {
          return `<li class="tree-group-label"><button type="button" class="tree-group-toggle" data-ontology-group="${esc(g.key)}">${esc(title)}</button></li>`;
        }
        return `<li class="tree-group-label"><button type="button" class="tree-group-toggle" data-ontology-group="${esc(g.key)}">${esc(title)}</button></li>${items || `<li class="tree-item tree-item-muted">${esc(t("common.noData"))}</li>`}`;
      })
      .join("");
    dom.ontologyEntityTree.querySelectorAll("[data-ontology-group]").forEach((node) => {
      node.addEventListener("click", () => {
        const key = String(node.getAttribute("data-ontology-group") || "");
        localState.ontologyGroupCollapsed[key] = !Boolean(localState.ontologyGroupCollapsed[key]);
        scheduleRender();
      });
    });
    dom.ontologyEntityTree.querySelectorAll("[data-entity-id]").forEach((node) => node.addEventListener("click", () => selectOntologyEntity(node.getAttribute("data-entity-id") || "")));

    renderKV(dom.ontologySummary, [
      { key: t("inspector.fields.name"), value: parsed.meta?.ontologyName || file?.filename || "-" },
      { key: "Namespace", value: parsed.meta?.namespace || "-" },
      { key: "Prefixes", value: (parsed.meta?.prefixes || []).join(", ") || "-" },
      { key: "Classes", value: parsed.stats?.classes ?? 0 },
      { key: "Object Properties", value: parsed.stats?.objectProperties ?? 0 },
      { key: "Data Properties", value: parsed.stats?.dataProperties ?? 0 },
      { key: "Individuals", value: parsed.stats?.individuals ?? 0 },
      { key: "Constraints", value: parsed.stats?.constraints ?? 0 },
      { key: t("inspector.fields.status"), value: parsed.meta?.parseMode || "-" },
    ]);
  }

  dom.ontologyLoadLog.textContent = ontologyStore.getState().loadLogs.slice(-120).join("\n");
}

function renderFileTable() {
  renderTable(
    dom.fileTable,
    fileStore.getState().files,
    [
      { key: "filename", label: t("files.columns.name") },
      { key: "file_type", label: t("files.columns.type") },
      { key: "size_bytes", label: t("files.columns.size"), render: (r) => bytes(r.size_bytes) },
      { key: "status", label: t("files.columns.status") },
      { key: "overall_label", label: t("files.columns.validation"), render: (r) => r.overall_label || "UNKNOWN" },
      { key: "score", label: t("files.columns.score"), render: (r) => r.score ?? "-" },
      { key: "blocked_on_load", label: t("files.columns.blocked"), render: (r) => (r.blocked_on_load ? t("common.yes") : t("common.no")) },
      { key: "last_validation_at", label: t("files.columns.validatedAt"), render: (r) => timeText(r.last_validation_at) },
      { key: "uploaded_at", label: t("files.columns.uploaded"), render: (r) => timeText(r.uploaded_at) },
      {
        key: "__actions",
        label: t("files.columns.actions"),
        raw: true,
        render: (r) =>
          `<button class="ide-btn file-remove-btn" data-stop-row-click="1" data-file-remove="${esc(r.file_id)}">${esc(t("files.remove"))}</button>`,
      },
    ],
    {
      rowId: "file_id",
      activeRowId: fileStore.getState().activeFileId,
      onRowClick: async (id) => {
        selectFile(id);
        await loadFilePreview(id, fileStore.getState().previewPageByFileId[id] || 1);
        await loadFileReport(id);
      },
      afterRender: (table) => {
        table.querySelectorAll("[data-file-remove]").forEach((node) => {
          node.addEventListener("click", async () => {
            const id = String(node.getAttribute("data-file-remove") || "");
            await removeFile(id);
          });
        });
      },
      emptyText: t("files.empty"),
    },
  );
}

function renderFilePreview() {
  const file = selectedFile();
  const preview = file ? fileStore.getState().previews[file.file_id] : null;

  dom.filePreviewEmbedWrap.classList.add("hidden");
  dom.filePreviewTableWrap.classList.add("hidden");
  dom.filePreviewContent.classList.remove("hidden");
  dom.filePreviewEmbed.src = "";
  dom.filePreviewMeta.textContent = "";
  dom.filePreviewContent.textContent = "";

  if (!file) {
    dom.filePreviewMeta.textContent = t("files.noActive");
    dom.filePreviewContent.textContent = t("common.noData");
    return;
  }
  if (!preview) {
    dom.filePreviewMeta.textContent = `${file.filename} | ${t("files.previewPending")}`;
    dom.filePreviewContent.textContent = t("files.previewPending");
    return;
  }

  const meta = [`${t("files.columns.type")}: ${file.file_type}`, `${t("files.columns.size")}: ${bytes(file.size_bytes)}`];
  if (preview.page) meta.push(`${t("files.page")}: ${preview.page}/${preview.total_pages || 1}`);
  dom.filePreviewMeta.textContent = meta.join(" | ");

  if (preview.mode === "raw_embed") {
    dom.filePreviewEmbedWrap.classList.remove("hidden");
    dom.filePreviewContent.classList.add("hidden");
    dom.filePreviewEmbed.src = preview.content_url || fileImportService.getContentUrl(file.file_id);
    return;
  }
  if (preview.mode === "table") {
    dom.filePreviewTableWrap.classList.remove("hidden");
    dom.filePreviewContent.classList.add("hidden");
    const cols = (preview.headers || []).map((h) => ({ key: h, label: h }));
    renderTable(dom.filePreviewTable, preview.rows || [], cols, { emptyText: t("common.noData") });
    return;
  }
  if (preview.mode === "json") {
    dom.filePreviewContent.textContent = pretty(preview.value || {});
    return;
  }
  dom.filePreviewContent.textContent = String(preview.text || "");
}

function renderFileWorkspace() {
  renderFileTable();
  renderFilePreview();
  renderValidationCheckPanel();
}

function renderExtractionWorkspace() {
  const o = ontologyStore.getState();
  const f = fileStore.getState();
  const e = extractionStore.getState();
  const draft = e.draft;

  dom.extractOntologySelect.innerHTML = o.files.length
    ? o.files.map((item) => `<option value="${esc(item.file_id)}" ${item.file_id === o.activeOntologyId ? "selected" : ""}>${esc(item.filename)}</option>`).join("")
    : `<option value="">${esc(t("common.noOntology"))}</option>`;

  Array.from(dom.extractTargetsWrap.querySelectorAll("input[type='checkbox']")).forEach((n) => {
    n.checked = draft.targets.includes(n.value);
  });

  dom.extractFileList.innerHTML = f.files.length
    ? f.files
        .map((file) => {
          const checked = f.extractionSelections[file.file_id] ? "checked" : "";
          return `<li><label><input data-file-select="${esc(file.file_id)}" type="checkbox" ${checked} /> ${esc(file.filename)} <span class="meta-text">[${esc(file.file_type)}]</span></label></li>`;
        })
        .join("")
    : `<li>${esc(t("files.empty"))}</li>`;

  dom.extractFileList.querySelectorAll("input[data-file-select]").forEach((n) => {
    n.addEventListener("change", () => {
      const id = n.getAttribute("data-file-select") || "";
      fileStore.setExtractionSelected(id, Boolean(n.checked));
      workspaceLogger.extract(`input_file_toggle file_id=${id} checked=${Boolean(n.checked)}`);
    });
  });

  const deepseekEnabled = Boolean(draft.deepseek?.enabled);
  const runtimeMode = resolveRuntimeMode(deepseekEnabled);
  const deepseekSummary = deepseekEnabled
    ? {
      model: resolveDeepSeekModel(draft.deepseek),
      temperature: draft.deepseek?.temperature ?? "-",
      responseFormat: draft.deepseek?.responseFormat || "-",
    }
    : null;

  const layoutInfo = renderExtractionTwoRowLayout(dom.extractionWorkbenchRoot, {
    deepseekEnabled,
  });
  const layoutSignature = `${layoutInfo.layout}:${deepseekEnabled ? "deepseek" : "standard"}`;
  if (localState.extractionLayoutMode !== layoutSignature) {
    localState.extractionLayoutMode = layoutSignature;
    workspaceLogger.ui(`[EXTRACTION_LAYOUT] template=${layoutInfo.layout}`);
    workspaceLogger.ui(`[EXTRACTION_LAYOUT] top_left=${layoutInfo.areas.topLeft}`);
    workspaceLogger.ui(`[EXTRACTION_LAYOUT] top_right=${layoutInfo.areas.topRight}`);
    workspaceLogger.ui(`[EXTRACTION_LAYOUT] bottom=${layoutInfo.areas.bottom}`);
    workspaceLogger.ui(`[EXTRACTION_LAYOUT] ratio top=${layoutInfo.ratios.top.toFixed(2)} bottom=${layoutInfo.ratios.bottom.toFixed(2)}`);
    if (deepseekEnabled) {
      workspaceLogger.ui("[EXTRACTION_LAYOUT] panel=deepseek_prompt_strategy span=wide");
    }
  }

  renderExtractionInputPanel(dom.extractionInputPanel, {
    ontologyCount: o.files.length,
    fileCount: f.files.length,
    selectedFileCount: extractionFiles().length,
  });
  renderExtractionTaskSummaryPanel(dom.extractionTaskSummaryPanel, {
    deepseekEnabled,
    activeJobId: e.activeJobId,
  });

  renderExtractionToolbar(dom.extractionToolbarHost, {
    t,
    language: lang(),
    mode: draft.mode,
    output: draft.output,
    granularity: draft.granularity,
    deepseekEnabled,
    deepseekSummary,
    onModeChange: (value) => extractionStore.updateDraft({ mode: value }),
    onOutputChange: (value) => extractionStore.updateDraft({ output: value }),
    onGranularityChange: (value) => changeGranularity(value),
    onDeepSeekToggle: (enabled) => toggleDeepSeek(enabled),
    onStart: () => startExtractionJob(),
  });

  renderDeepSeekBottomWorkbench(dom.deepseekWorkbenchHost, {
    enabled: deepseekEnabled,
    config: draft.deepseek || {},
    t,
    onFieldChange: (field, value) => updateDeepSeekField(field, value),
  });

  renderTable(
    dom.extractionJobTable,
    e.jobs,
    [
      { key: "id", label: t("extraction.columns.id") },
      { key: "status", label: t("extraction.columns.status") },
      { key: "progress", label: t("extraction.columns.progress"), render: (r) => `${r.progress || 0}%` },
      { key: "stage", label: t("extraction.columns.stage") },
      { key: "granularity", label: t("extraction.columns.granularity"), render: (r) => granularityLabel(r.granularity) },
      { key: "runtimeMode", label: t("extraction.columns.mode"), render: (r) => runtimeModeLabel(r.runtimeMode) },
      { key: "model", label: t("extraction.columns.model"), render: (r) => (r.runtimeMode === "deepseek" ? r.deepseek?.model || "-" : "-") },
      {
        key: "temperature",
        label: t("extraction.columns.temperature"),
        render: (r) => (r.runtimeMode === "deepseek" ? r.deepseek?.temperature ?? "-" : "-"),
      },
      { key: "createdAt", label: t("extraction.columns.created"), render: (r) => timeText(r.createdAt) },
    ],
    {
      rowId: "id",
      activeRowId: e.activeJobId,
      onRowClick: (id) => {
        selectExtractionJob(id);
        setActionHelp("start_extraction");
      },
      emptyText: t("extraction.noJob"),
    },
  );
}
function renderGraphWorkspace() {
  const state = graphStore.getState();
  const filter = state.layerFilter || "all";
  dom.graphFilterType.value = filter;

  const nodes = state.nodes.filter((n) => filter === "all" || n.type === filter);
  const edges = state.edges.filter((e) => filter === "all" || e.type === filter);

  dom.graphCanvas.textContent = `${t("graph.placeholder")}\nnodes=${nodes.length} edges=${edges.length}`;

  renderTable(
    dom.graphNodeTable,
    nodes,
    [
      { key: "id", label: t("graph.columns.id") },
      { key: "type", label: t("graph.columns.type") },
      { key: "label", label: t("graph.columns.label") },
      { key: "confidence", label: t("graph.columns.confidence"), render: (r) => r.confidence ?? "-" },
    ],
    {
      rowId: "id",
      activeRowId: uiStore.getState().selectedGraphNodeId,
      onRowClick: (id) => selectGraphNode(id),
      emptyText: t("graph.emptyNodes"),
    },
  );

  renderTable(
    dom.graphEdgeTable,
    edges,
    [
      { key: "id", label: t("graph.columns.id") },
      { key: "source", label: t("graph.columns.source") },
      { key: "target", label: t("graph.columns.target") },
      { key: "type", label: t("graph.columns.type") },
      { key: "confidence", label: t("graph.columns.confidence"), render: (r) => r.confidence ?? "-" },
    ],
    {
      rowId: "id",
      activeRowId: uiStore.getState().selectedGraphEdgeId,
      onRowClick: (id) => selectGraphEdge(id),
      emptyText: t("graph.emptyEdges"),
    },
  );
}

function renderReviewTable(target, rows, cols, type) {
  if (!target) return;
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    target.innerHTML = `<thead><tr><th>${esc(t("common.info"))}</th></tr></thead><tbody><tr><td>${esc(t("review.empty"))}</td></tr></tbody>`;
    return;
  }
  const head = `<thead><tr>${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}<th>${esc(t("review.actions"))}</th></tr></thead>`;
  const body = `<tbody>${list
    .map((row) => {
      const cells = cols.map((c) => `<td>${esc(c.render ? c.render(row) : row[c.key] ?? "-")}</td>`).join("");
      const actions = [
        `<button class="ide-btn" data-type="${type}" data-id="${esc(row.id)}" data-status="accepted">${esc(t("review.accept"))}</button>`,
        `<button class="ide-btn" data-type="${type}" data-id="${esc(row.id)}" data-status="rejected">${esc(t("review.reject"))}</button>`,
        `<button class="ide-btn" data-type="${type}" data-id="${esc(row.id)}" data-status="pending">${esc(t("review.defer"))}</button>`,
      ].join(" ");
      return `<tr>${cells}<td>${actions}</td></tr>`;
    })
    .join("")}</tbody>`;
  target.innerHTML = head + body;

  target.querySelectorAll("button[data-status]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-id") || "";
      const status = btn.getAttribute("data-status") || "pending";
      const itemType = btn.getAttribute("data-type") || type;
      graphStore.updateReviewStatus(itemType, id, status);
      workspaceLogger.review(`candidate_update type=${itemType} id=${id} status=${status}`);
    });
  });
}

function renderReviewWorkspace() {
  const review = graphStore.getState().review;
  renderReviewTable(dom.reviewEntityTable, review.entities, [
    { key: "name", label: t("review.columns.name") },
    { key: "type", label: t("review.columns.type") },
    { key: "confidence", label: t("review.columns.confidence") },
    { key: "status", label: t("review.columns.status") },
  ], "entity");

  renderReviewTable(dom.reviewRelationTable, review.relations, [
    { key: "source", label: t("review.columns.source") },
    { key: "target", label: t("review.columns.target") },
    { key: "relationType", label: t("review.columns.relationType") },
    { key: "confidence", label: t("review.columns.confidence") },
    { key: "status", label: t("review.columns.status") },
  ], "relation");

  renderReviewTable(dom.reviewCircuitTable, review.circuits, [
    { key: "name", label: t("review.columns.name") },
    { key: "family", label: t("review.columns.family") },
    { key: "confidence", label: t("review.columns.confidence") },
    { key: "status", label: t("review.columns.status") },
  ], "circuit");
}

function renderCrawlerWorkspace() {
  dom.crawlerStatus.textContent = localState.crawlerLastStatus || t("crawler.pending");
}

function renderSettingsWorkspace() {
  const s = settingsStore.getState();
  renderSettingsPanel(dom.settingsPanelHost, {
    language: s.language,
    appearance: s.appearance,
    defaultGranularity: s.extractionPreferences.defaultGranularity,
    defaultOutput: s.extractionPreferences.defaultOutput,
    workspacePreferences: s.workspacePreferences,
    t,
    onChange(next) {
      applyLanguage(next, "settings_panel");
    },
    onApplyLight() {
      applyTheme("light-workspace", "settings_panel");
      workspaceLogger.ui("[THEME] apply background=light panel=white console=soft-muted");
    },
    onGranularityChange(next) {
      settingsStore.setDefaultGranularity(next);
      changeGranularity(next, "settings_default");
    },
    onOutputChange(next) {
      settingsStore.setDefaultOutput(next);
      extractionStore.updateDraft({ output: next });
    },
    onWorkspacePrefChange(key, value) {
      settingsStore.setWorkspacePreference(key, value);
      if (key === "defaultMainTab" && !restoringSnapshot) uiStore.setActiveMainTab(value);
      workspaceLogger.ui(`workspace_pref_change key=${key} value=${String(value)}`);
    },
  });
}

function inspectorLines() {
  const ui = uiStore.getState();
  const mode = ui.inspectorMode || "none";

  if (mode === "ontology_entity") {
    const entity = flattenOntology(activeParsedOntology()).find((x) => x.id === ontologyStore.getState().selectedEntityId);
    if (!entity) return [{ label: t("common.info"), value: t("common.noneSelected") }];
    return [
      { label: t("inspector.fields.name"), value: entity.label || entity.id },
      { label: t("inspector.fields.type"), value: entity.__type || entity.type || "-" },
      { label: "IRI", value: entity.iri || "-" },
      { label: "Parent", value: entity.parent || "-" },
      { label: t("inspector.fields.description"), value: entity.description || "-" },
    ];
  }
  if (mode === "file") {
    const file = selectedFile();
    const report = file ? fileStore.getState().reports[file.file_id]?.report : null;
    if (!file) return [{ label: t("common.info"), value: t("common.noneSelected") }];
    return [
      { label: t("inspector.fields.name"), value: file.filename },
      { label: t("inspector.fields.type"), value: file.file_type },
      { label: t("inspector.fields.status"), value: file.status || "-" },
      { label: t("inspector.fields.source"), value: file.original_path || "-" },
      { label: t("files.columns.validation"), value: report?.overall_label || file.overall_label || "UNKNOWN" },
      { label: "Score", value: report?.score ?? file.score ?? "-" },
      { label: "DeepSeek Source", value: report?.validation_trace?.llm_initial?.config_source || "-" },
      { label: t("files.columns.validatedAt"), value: timeText(file.last_validation_at) },
      { label: "Readiness", value: report?.gate_decision?.allow_extract ? "ready" : "check_required" },
      { label: "Summary", value: report?.summary_cn || file.summary_cn || "-" },
      { label: "Blocked", value: file.blocked_on_load ? t("common.yes") : t("common.no") },
    ];
  }
  if (mode === "extraction_job") {
    const job = activeJob();
    if (!job) return [{ label: t("common.info"), value: t("common.noneSelected") }];
    return [
      { label: "Job ID", value: job.id },
      { label: t("inspector.fields.status"), value: job.status },
      { label: t("extraction.summary.mode"), value: runtimeModeLabel(job.runtimeMode) },
      { label: t("extraction.summary.model"), value: job.runtimeMode === "deepseek" ? job.deepseek?.model || "-" : "-" },
      { label: "DeepSeek Source", value: job.runtimeMode === "deepseek" ? (job.deepseek?.useTaskOverride ? "override" : "global") : "-" },
      { label: t("extraction.summary.temperature"), value: job.runtimeMode === "deepseek" ? job.deepseek?.temperature ?? "-" : "-" },
      { label: t("extraction.summary.responseFormat"), value: job.runtimeMode === "deepseek" ? job.deepseek?.responseFormat || "-" : "-" },
      { label: t("extraction.granularity.selected"), value: granularityLabel(job.granularity) },
      { label: t("extraction.granularity.entityTable"), value: job.tableMapping?.entityTable || "-" },
      { label: t("extraction.granularity.relationTable"), value: job.tableMapping?.relationTable || "-" },
      { label: t("extraction.granularity.circuitTable"), value: job.tableMapping?.circuitTable || "-" },
      { label: "Progress", value: `${job.progress || 0}%` },
      { label: "Stage", value: job.stage || "-" },
    ];
  }
  if (mode === "graph_node") {
    const node = graphStore.getState().nodes.find((x) => x.id === ui.selectedGraphNodeId);
    if (!node) return [{ label: t("common.info"), value: t("common.noneSelected") }];
    return [
      { label: "Node ID", value: node.id },
      { label: t("inspector.fields.type"), value: node.type },
      { label: t("inspector.fields.name"), value: node.label || "-" },
      { label: "Confidence", value: node.confidence ?? "-" },
    ];
  }
  if (mode === "graph_edge") {
    const edge = graphStore.getState().edges.find((x) => x.id === ui.selectedGraphEdgeId);
    if (!edge) return [{ label: t("common.info"), value: t("common.noneSelected") }];
    return [
      { label: "Edge ID", value: edge.id },
      { label: t("graph.columns.source"), value: edge.source },
      { label: t("graph.columns.target"), value: edge.target },
      { label: t("inspector.fields.type"), value: edge.type },
      { label: "Confidence", value: edge.confidence ?? "-" },
    ];
  }
  if (mode === "warning") return [{ label: t("inspector.fields.detail"), value: t("extraction.blocked") }];
  return [{ label: t("common.info"), value: t("common.noneSelected") }];
}

function renderInspectorPanel() {
  const mode = uiStore.getState().inspectorMode || "none";
  dom.inspectorMode.textContent = `${t("inspector.modeLabel")}: ${mode}`;
  dom.inspectorContent.textContent = inspectorLines().map((x) => `${x.label}: ${x.value ?? "-"}`).join("\n");

  const helpContext = {
    language: lang(),
    ontologyReady: Boolean(ontologyStore.getState().activeOntologyId),
    selectedFileId: fileStore.getState().activeFileId,
    granularity: extractionStore.getState().draft.granularity,
    runtime: localState.runtimeStatus,
  };
  dom.inspectorActionHelp.textContent = actionHelpTemplate(localState.actionId, helpContext);
}

function renderBottomPanel() {
  const ui = uiStore.getState();
  const logs = logStore.listBy();
  const logsText = logStore.toText() || t("common.noLog");

  dom.bottomViews.logs.textContent = logsText;
  dom.bottomViews.tasks.textContent =
    extractionStore
      .getState()
      .jobs.map(
        (job) =>
          `${job.id} | status=${job.status} | stage=${job.stage || "-"} | progress=${job.progress || 0}% | granularity=${job.granularity} | mode=${job.runtimeMode || "placeholder"} | model=${job.runtimeMode === "deepseek" ? job.deepseek?.model || "-" : "-"} | temperature=${job.runtimeMode === "deepseek" ? job.deepseek?.temperature ?? "-" : "-"}`,
      )
      .join("\n") || t("extraction.noJob");
  dom.bottomViews.problems.textContent =
    logs
      .filter((x) => x.level === "warn" || x.level === "error")
      .map((x) => `[${x.ts}] [${x.prefix}] ${x.message}`)
      .join("\n") || t("common.noProblem");
  dom.bottomViews.trace.textContent =
    logs
      .filter((x) => ["EXTRACT", "GRAPH", "REVIEW", "ONTOLOGY"].includes(x.prefix))
      .map((x) => `[${x.ts}] [${x.prefix}] ${x.message}`)
      .join("\n") || t("common.noTrace");

  dom.mainConsoleLog.textContent = logsText;

  dom.bottomTabs.forEach((btn) => btn.classList.toggle("active", btn.getAttribute("data-bottom-tab") === ui.activeBottomTab));
  Object.entries(dom.bottomViews).forEach(([k, node]) => {
    node.classList.toggle("active", k === ui.activeBottomTab);
    if (k === ui.activeBottomTab && settingsStore.getState().workspacePreferences.autoScrollLogs) node.scrollTop = node.scrollHeight;
  });
}

function renderTabsAndPanels() {
  const ui = uiStore.getState();
  dom.mainTabButtons.forEach((btn) => btn.classList.toggle("active", btn.getAttribute("data-main-tab") === ui.activeMainTab));
  dom.viewButtons.forEach((btn) => btn.classList.toggle("active", btn.getAttribute("data-main-tab") === ui.activeMainTab));
  dom.workbenchTabs.forEach((tab) => tab.classList.toggle("active", tab.id === ui.activeMainTab));
  Object.entries(ui.panelCollapseState || {}).forEach(([id, collapsed]) => {
    const node = document.getElementById(id);
    if (node) node.classList.toggle("open", !collapsed);
  });
}

function renderAll() {
  applyI18nToDom(t);
  document.title = t("app.title");
  renderTabsAndPanels();
  renderSidebarProjectExplorer();
  renderSidebarOntologyRules();
  renderSidebarDataSources();
  renderSidebarSessions();
  renderOverview();
  renderOntologyWorkspace();
  renderFileWorkspace();
  renderExtractionWorkspace();
  renderGraphWorkspace();
  renderReviewWorkspace();
  renderCrawlerWorkspace();
  renderSettingsWorkspace();
  renderInspectorPanel();
  renderBottomPanel();
}

function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderAll();
  });
}

function bindEvents() {
  dom.btnImportOntology?.addEventListener("click", () => {
    setActionHelp("import_ontology");
    dom.inputImportOntology?.click();
  });
  dom.btnImportFiles?.addEventListener("click", () => {
    setActionHelp("import_files");
    dom.inputImportFiles?.click();
  });
  dom.btnNewTask?.addEventListener("click", () => {
    setActionHelp("new_task");
    setMainTab("tab-extraction");
  });
  dom.btnSaveWorkspace?.addEventListener("click", () => {
    setActionHelp("save_workspace");
    saveSnapshot();
  });
  dom.btnOpenSettings?.addEventListener("click", () => {
    setActionHelp("open_settings");
    setMainTab("tab-settings");
  });
  dom.btnThemeToggle?.addEventListener("click", () => {
    setActionHelp("open_settings");
    applyTheme("light-workspace", "toolbar");
    setMainTab("tab-settings");
  });

  dom.btnRefreshOntology?.addEventListener("click", async () => {
    setActionHelp("refresh_ontology");
    const id = ontologyStore.getState().activeOntologyId;
    if (!id) {
      workspaceLogger.ontology("refresh_blocked reason=no_active_ontology", {}, "warn");
      return;
    }
    await ensureOntologyParsed(id);
    workspaceLogger.ontology(`refresh_done file_id=${id}`);
  });

  dom.btnGraphFit?.addEventListener("click", () => {
    setActionHelp("graph_fit");
    workspaceLogger.graph("fit_view");
  });
  dom.btnGraphReset?.addEventListener("click", () => {
    setActionHelp("graph_reset");
    graphStore.setFilter("all");
    workspaceLogger.graph("graph_reset");
  });

  dom.btnCrawlerCreateJob?.addEventListener("click", async () => {
    setActionHelp("crawler_create_job");
    try {
      const result = await apiJson("/api/crawler/jobs", "POST", {
        source_type: String(dom.crawlerSourceType?.value || "url"),
        source_input: String(dom.crawlerSourceInput?.value || "").trim(),
      });
      localState.crawlerLastStatus = pretty(result);
      workspaceLogger.import(`crawler_deferred status=${result.status || "unknown"}`);
    } catch (e) {
      localState.crawlerLastStatus = String(e);
      workspaceLogger.import(`crawler_create_failed error=${String(e)}`, {}, "error");
    }
    scheduleRender();
  });

  dom.inputImportOntology?.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    try {
      await handleImportFiles(files, "ontology");
    } catch (e) {
      workspaceLogger.import(`ontology_upload_failed error=${String(e)}`, {}, "error");
    }
  });

  dom.inputImportFiles?.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    try {
      await handleImportFiles(files, "files");
    } catch (e) {
      workspaceLogger.import(`file_upload_failed error=${String(e)}`, {}, "error");
    }
  });

  dom.mainTabButtons.forEach((btn) => btn.addEventListener("click", () => setMainTab(btn.getAttribute("data-main-tab") || "tab-overview")));
  dom.viewButtons.forEach((btn) => btn.addEventListener("click", () => setMainTab(btn.getAttribute("data-main-tab") || "tab-overview")));
  dom.bottomTabs.forEach((btn) => btn.addEventListener("click", () => setBottomTab(btn.getAttribute("data-bottom-tab") || "logs")));
  dom.sectionToggles.forEach((btn) => btn.addEventListener("click", () => uiStore.togglePanel(btn.getAttribute("data-target"))));

  dom.extractOntologySelect?.addEventListener("change", (event) => {
    const fileId = String(event.target.value || "");
    ontologyStore.setActiveOntology(fileId);
    uiStore.setState({ inspectorMode: "ontology_entity", selectedResourceId: fileId });
  });
  dom.extractTargetsWrap?.addEventListener("change", () => extractionStore.updateDraft({ targets: extractionTargets() }));

  dom.graphFilterType?.addEventListener("change", (event) => {
    const value = String(event.target.value || "all");
    graphStore.setFilter(value);
    workspaceLogger.graph(`filter_change type=${value}`);
  });

  dom.btnFilePreviewPrev?.addEventListener("click", async () => {
    setActionHelp("refresh_preview");
    const id = fileStore.getState().activeFileId;
    if (!id) return;
    const page = fileStore.getState().previewPageByFileId[id] || 1;
    await loadFilePreview(id, Math.max(1, page - 1));
  });
  dom.btnFilePreviewNext?.addEventListener("click", async () => {
    setActionHelp("refresh_preview");
    const id = fileStore.getState().activeFileId;
    if (!id) return;
    const preview = fileStore.getState().previews[id];
    const page = fileStore.getState().previewPageByFileId[id] || 1;
    await loadFilePreview(id, Math.min(Number(preview?.total_pages || 1), page + 1));
  });

  dom.ontologyFilterInput?.addEventListener("input", (event) => {
    const keyword = String(event.target.value || "");
    localState.ontologyFilterKeyword = keyword;
    workspaceLogger.ontology(`[TREE] filter keyword=${normalizeKeyword(keyword)}`);
    scheduleRender();
  });
}

function bindStores() {
  uiStore.subscribe(() => {
    if (settingsStore.getState().workspacePreferences.rememberPanelCollapse) saveSnapshot();
    scheduleRender();
  });
  ontologyStore.subscribe(scheduleRender);
  fileStore.subscribe(scheduleRender);
  extractionStore.subscribe(scheduleRender);
  graphStore.subscribe(scheduleRender);
  logStore.subscribe(scheduleRender);
  settingsStore.subscribe(scheduleRender);
}

async function bootstrap() {
  const settings = settingsStore.getState();
  workspaceLogger.ui(`[THEME] init theme=${settings.appearance || "light-workspace"}`);
  applyTheme(settings.appearance || "light-workspace", "init");
  workspaceLogger.ui("[THEME] apply background=light panel=white console=soft-muted");
  applyLanguage(settings.language || "zh-CN", "init");

  extractionStore.setGranularityFromDefault(settings.extractionPreferences.defaultGranularity || "coarse");
  extractionStore.updateDraft({ output: settings.extractionPreferences.defaultOutput || "triples" });

  if (settings.workspacePreferences?.defaultMainTab) uiStore.setActiveMainTab(settings.workspacePreferences.defaultMainTab);
  restoreSnapshot();

  await loadRuntimeStatus();
  await refreshFilesAndOntology({ parseOntologies: false });

  const fileId = fileStore.getState().activeFileId;
  if (fileId) {
    await loadFilePreview(fileId, 1);
    await loadFileReport(fileId);
  }

  bindEvents();
  bindStores();
  renderAll();
  workspaceLogger.ui("workbench_ready");
}

bootstrap().catch((e) => {
  workspaceLogger.ui(`bootstrap_failed error=${String(e)}`, {}, "error");
  renderAll();
});
