const state = {
  lang: "zh",
  currentJobId: "",
  currentPreviewJobId: "",
  pollingTimer: null,
  latestPreviewBundle: null,
  selectedMajorPane: "file_preview",
  fileCenter: {
    files: [],
    stats: {},
    reports: {},
    activeFileId: "",
    preview: null,
    previewPage: 1,
    previewPageSize: 500,
  },
  lastJobSnapshot: { status: "idle", current_stage: "-", completed_steps: 0, total_steps: 0, logs: [] },
};

const SECRET_MASK = "***";
const STRUCTURED_EXT = new Set(["xlsx", "csv", "tsv", "json", "jsonl"]);
const MAJOR_PANES = [
  "file_preview",
  "major_regions",
  "major_circuits",
  "cross_pass",
  "cross_fail",
  "rejected",
  "report_crosscheck",
  "report_coverage",
  "report_mismatch",
  "files_list",
  "validation_center",
];

const I18N = {
  zh: {
    title: "NeuroKG 工作台",
    brand_title: "NeuroKG 工作台",
    btn_import_excel: "导入文件",
    btn_import_ontology: "导入本体",
    btn_rebuild_schema: "重建 Schema",
    btn_start_extract: "开始提取",
    btn_load_db: "写入数据库",
    btn_open_reports: "打开报告",
    btn_save_settings: "保存设置",
    major_title: "主脑区流程",
    major_file_preview: "文件预览",
    major_regions: "主脑区",
    major_circuits: "回路",
    major_cross_pass: "互证通过连接",
    major_cross_fail: "互证失败连接",
    major_rejected: "Rejected",
    report_crosscheck: "互证报告",
    report_coverage: "覆盖报告",
    report_mismatch: "不一致报告",
    major_files_list: "文件列表",
    major_validation_center: "校验中心",
    module_major: "主脑区",
    module_anatomy: "解剖层",
    module_sub: "Sub",
    module_allen: "Allen",
    module_crawler: "爬虫",
    module_settings: "设置",
    crawler_title: "爬虫",
    crawler_source_type: "来源类型",
    crawler_source_input: "来源输入",
    anatomy_title: "解剖层",
    anatomy_desc: "固定基础实体：Organism / AnatomicalSystem / Organ / BrainDivision。",
    waiting_preview_or_load: "等待预览或入库...",
    sub_title: "Sub 工作区",
    sub_desc: "Sub 层工作区已预留，本期不接入真实提取。",
    sub_item_extract: "预留提取入口",
    sub_item_validate: "预留校验入口",
    sub_item_load: "预留入库入口",
    allen_title: "Allen 工作区",
    allen_desc: "Allen 层工作区已预留，本期不接入真实提取。",
    allen_item_extract: "预留提取入口",
    allen_item_validate: "预留校验入口",
    allen_item_load: "预留入库入口",
    settings_title: "设置",
    settings_database: "数据库",
    settings_deepseek: "DeepSeek",
    settings_input_paths: "输入路径",
    settings_ui: "界面",
    field_host: "Host",
    field_port: "Port",
    field_database: "Database",
    field_user: "User",
    field_password: "Password",
    field_schema: "Schema",
    field_api_key: "API Key",
    field_base_url: "Base URL",
    field_model: "Model",
    field_use_deepseek: "启用 DeepSeek",
    field_batch_size: "批大小",
    field_excel_path: "主输入文件路径",
    field_sheet_index: "Sheet Index",
    field_header_row: "Header Row",
    field_ontology_path: "本体路径",
    field_language: "语言",
    lang_zh: "中文",
    lang_en: "English",
    language_desc: "切换后立即生效，并保存在本地浏览器。",
    status_idle: "任务: idle",
    status_stage_default: "阶段: -",
    status_db_default: "数据库: -",
    status_job_prefix: "任务",
    status_stage_prefix: "阶段",
    status_db_prefix: "数据库",
    status_connected: "已连接",
    status_disconnected: "未连接",
    msg_no_data: "暂无数据",
    msg_validation_center_hint: "请先在“文件列表”中选择文件。",
    msg_validation_center_label: "标注",
    msg_validation_center_plan: "处理方案",
    msg_validation_center_gate: "门禁结果",
    msg_selected_pane: "当前视图",
    msg_file_uploaded: "文件已上传",
    msg_file_validate_started: "开始文件校验",
    msg_file_validate_done: "文件校验完成",
    msg_file_validate_error: "文件校验失败",
    msg_file_auto_fix_done: "自动低风险处理完成",
    msg_file_blocked_on_load: "该文件会阻断入库",
    msg_file_list_loaded: "文件中心已刷新",
    msg_uploaded_count: "上传文件数",
    msg_load_blocked_validation: "存在 FAIL 文件，已阻断入库",
    msg_run_preview_first: "请先开始提取。",
    msg_run_preview_for_reports: "请先执行提取。",
    msg_unstructured_extract_block: "开始提取仅支持结构化文件（xlsx/csv/tsv/json/jsonl）。",
    msg_preview_page_hint: "翻页快捷键：[,] 上一页 / [.] 下一页",
    msg_preview_run_error: "提取运行失败",
    msg_load_error: "入库失败",
    msg_excel_import_error: "文件导入失败",
    msg_ontology_import_error: "本体导入失败",
    msg_schema_rebuild_error: "Schema 重建失败",
    msg_open_reports_error: "打开报告失败",
    msg_save_settings_error: "保存设置失败",
    msg_reports_path: "报告路径",
    crawler_deferred_desc: "Crawler 在 V2.1 为暂缓态（deferred），本阶段不执行抓取任务。",
    crawler_waiting: "Crawler 模块当前为 deferred。",
  },
  en: {
    title: "NeuroKG Workbench",
    brand_title: "NeuroKG Workbench",
    btn_import_excel: "Import File",
    btn_import_ontology: "Import Ontology",
    btn_rebuild_schema: "Rebuild Schema",
    btn_start_extract: "Start Extraction",
    btn_load_db: "Load To DB",
    btn_open_reports: "Open Reports",
    btn_save_settings: "Save Settings",
    major_title: "Major Pipeline",
    major_file_preview: "File Preview",
    major_regions: "Major Regions",
    major_circuits: "Major Circuits",
    major_cross_pass: "Cross Pass Connections",
    major_cross_fail: "Cross Fail Connections",
    major_rejected: "Rejected",
    report_crosscheck: "Crosscheck Report",
    report_coverage: "Coverage Report",
    report_mismatch: "Mismatch Report",
    major_files_list: "File List",
    major_validation_center: "Validation Center",
    module_major: "Major",
    module_anatomy: "Anatomy",
    module_sub: "Sub",
    module_allen: "Allen",
    module_crawler: "Crawler",
    module_settings: "Settings",
    crawler_title: "Crawler",
    crawler_source_type: "Source Type",
    crawler_source_input: "Source Input",
    anatomy_title: "Anatomy",
    anatomy_desc: "Fixed base entities: Organism / AnatomicalSystem / Organ / BrainDivision.",
    waiting_preview_or_load: "Waiting for preview or load...",
    sub_title: "Sub Workbench",
    sub_desc: "Sub-level workbench is reserved. Real extraction flow is not connected in this phase.",
    sub_item_extract: "Reserved extraction entry",
    sub_item_validate: "Reserved validation entry",
    sub_item_load: "Reserved load entry",
    allen_title: "Allen Workbench",
    allen_desc: "Allen-level workbench is reserved. Real extraction flow is not connected in this phase.",
    allen_item_extract: "Reserved extraction entry",
    allen_item_validate: "Reserved validation entry",
    allen_item_load: "Reserved load entry",
    settings_title: "Settings",
    settings_database: "Database",
    settings_deepseek: "DeepSeek",
    settings_input_paths: "Input Paths",
    settings_ui: "UI",
    field_host: "Host",
    field_port: "Port",
    field_database: "Database",
    field_user: "User",
    field_password: "Password",
    field_schema: "Schema",
    field_api_key: "API Key",
    field_base_url: "Base URL",
    field_model: "Model",
    field_use_deepseek: "Use DeepSeek",
    field_batch_size: "Batch Size",
    field_excel_path: "Primary Input Path",
    field_sheet_index: "Sheet Index",
    field_header_row: "Header Row",
    field_ontology_path: "Ontology Path",
    field_language: "Language",
    lang_zh: "Chinese",
    lang_en: "English",
    language_desc: "Applied immediately and saved in browser local settings.",
    status_idle: "Job: idle",
    status_stage_default: "Stage: -",
    status_db_default: "DB: -",
    status_job_prefix: "Job",
    status_stage_prefix: "Stage",
    status_db_prefix: "DB",
    status_connected: "connected",
    status_disconnected: "disconnected",
    msg_no_data: "No data",
    msg_validation_center_hint: "Select a file in File List first.",
    msg_validation_center_label: "Label",
    msg_validation_center_plan: "Treatment Plan",
    msg_validation_center_gate: "Gate Decision",
    msg_selected_pane: "Selected view",
    msg_file_uploaded: "File uploaded",
    msg_file_validate_started: "File validation started",
    msg_file_validate_done: "File validation completed",
    msg_file_validate_error: "File validation failed",
    msg_file_auto_fix_done: "Auto-fix completed",
    msg_file_blocked_on_load: "This file blocks load",
    msg_file_list_loaded: "File center refreshed",
    msg_uploaded_count: "Uploaded files",
    msg_load_blocked_validation: "Load blocked by FAIL files",
    msg_run_preview_first: "Run extraction before loading.",
    msg_run_preview_for_reports: "Run extraction first.",
    msg_unstructured_extract_block: "Start Extraction only supports structured files (xlsx/csv/tsv/json/jsonl).",
    msg_preview_page_hint: "Paging hotkeys: [,] previous / [.] next",
    msg_preview_run_error: "Extraction run error",
    msg_load_error: "Load error",
    msg_excel_import_error: "File import error",
    msg_ontology_import_error: "Ontology import error",
    msg_schema_rebuild_error: "Schema rebuild error",
    msg_open_reports_error: "Open reports error",
    msg_save_settings_error: "Save settings error",
    msg_reports_path: "Reports path",
    crawler_deferred_desc: "Crawler is deferred in V2.1 and does not execute jobs in this phase.",
    crawler_waiting: "Crawler module is deferred.",
  },
};

const qs = (id) => document.getElementById(id);
const t = (key) => (I18N[state.lang] || I18N.en)[key] || I18N.en[key] || key;
const extOf = (path) => {
  const s = String(path || "");
  const i = s.lastIndexOf(".");
  return i >= 0 ? s.slice(i + 1).toLowerCase() : "";
};

function escapeHtml(v) {
  return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function appendLog(message) {
  const node = qs("job-logs");
  if (!node) return;
  const lines = node.textContent ? node.textContent.split("\n").filter(Boolean) : [];
  lines.push(`[${new Date().toISOString()}] ${message}`);
  node.textContent = lines.slice(-200).join("\n");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const text = await response.text();
  let data = {};
  if (text.trim()) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!response.ok) throw new Error(`HTTP ${response.status} ${response.statusText}: ${text.slice(0, 280)}`);
    }
  }
  if (!response.ok) {
    const err = new Error(data.error || `Request failed: ${response.status}`);
    err.payload = data;
    throw err;
  }
  return data;
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/files/upload", { method: "POST", body: form });
  const text = await response.text();
  let data = {};
  if (text.trim()) data = JSON.parse(text);
  if (!response.ok) throw new Error(data.error || `Upload failed: ${response.status}`);
  return data;
}

function renderPre(id, value) {
  const node = qs(id);
  if (!node) return;
  node.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function renderTable(id, rows, keys = [], opts = {}) {
  const table = qs(id);
  if (!table) return;
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
    table.innerHTML = `<tr><td>${escapeHtml(t("msg_no_data"))}</td></tr>`;
    return;
  }
  const all = [...new Set([...keys, ...Object.keys(safeRows[0])])];
  const head = `<thead><tr>${all.map((k) => `<th>${escapeHtml(k)}</th>`).join("")}</tr></thead>`;
  const body = safeRows.map((row) => {
    const rowKey = opts.rowKey ? String(row[opts.rowKey] || "") : "";
    const attr = rowKey ? ` data-row-key="${escapeHtml(rowKey)}"` : "";
    const selected = rowKey && opts.selectedRowKey === rowKey ? " class=\"table-row-selected\"" : "";
    const cols = all.map((k) => `<td>${escapeHtml(typeof row[k] === "object" ? JSON.stringify(row[k]) : (row[k] ?? ""))}</td>`).join("");
    return `<tr${selected}${attr}>${cols}</tr>`;
  });
  table.innerHTML = `${head}<tbody>${body.join("")}</tbody>`;
  if (opts.rowKey && opts.onRowClick) {
    table.querySelectorAll("tbody tr[data-row-key]").forEach((tr) => {
      tr.addEventListener("click", () => opts.onRowClick(tr.dataset.rowKey || ""));
    });
  }
}

function switchModule(id) {
  document.querySelectorAll(".module-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.module === id));
  document.querySelectorAll(".module").forEach((mod) => mod.classList.toggle("active", mod.id === id));
}

function applyLanguage(lang) {
  state.lang = lang === "en" ? "en" : "zh";
  localStorage.setItem("ui_lang", state.lang);
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  const titleNode = document.querySelector("title[data-i18n]");
  if (titleNode) titleNode.textContent = t(titleNode.dataset.i18n);
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    if (node.tagName.toLowerCase() !== "title") node.textContent = t(node.dataset.i18n);
  });
  if (qs("ui-language")) qs("ui-language").value = state.lang;
  renderSelectedMajorPane();
}

function activeFileId() {
  const files = state.fileCenter.files || [];
  if (state.fileCenter.activeFileId && files.some((x) => x.file_id === state.fileCenter.activeFileId)) return state.fileCenter.activeFileId;
  const fail = files.find((x) => String(x.overall_label || "").toUpperCase() === "FAIL");
  const warn = files.find((x) => String(x.overall_label || "").toUpperCase() === "WARN");
  return (fail || warn || files[0] || {}).file_id || "";
}

function panelTitleKey(pane) {
  return {
    file_preview: "major_file_preview",
    major_regions: "major_regions",
    major_circuits: "major_circuits",
    cross_pass: "major_cross_pass",
    cross_fail: "major_cross_fail",
    rejected: "major_rejected",
    report_crosscheck: "report_crosscheck",
    report_coverage: "report_coverage",
    report_mismatch: "report_mismatch",
    files_list: "major_files_list",
    validation_center: "major_validation_center",
  }[pane] || "major_file_preview";
}

function updateJobUi(job) {
  state.lastJobSnapshot = {
    status: job.status || "idle",
    current_stage: job.current_stage || "-",
    completed_steps: Number(job.completed_steps || 0),
    total_steps: Number(job.total_steps || 0),
    logs: Array.isArray(job.logs) ? job.logs : [],
  };
  if (qs("job-status")) qs("job-status").textContent = `${t("status_job_prefix")}: ${state.lastJobSnapshot.status}`;
  if (qs("job-stage")) qs("job-stage").textContent = `${t("status_stage_prefix")}: ${state.lastJobSnapshot.current_stage}`;
  if (qs("progress-bar")) {
    const total = state.lastJobSnapshot.total_steps;
    const done = state.lastJobSnapshot.completed_steps;
    qs("progress-bar").style.width = `${total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0}%`;
  }
  if (qs("job-logs")) qs("job-logs").textContent = state.lastJobSnapshot.logs.slice(-80).join("\n");
}

function updateCounts() {
  const preview = state.latestPreviewBundle?.preview || {};
  const reports = state.latestPreviewBundle?.reports || {};
  const crossFail = [...(preview.cross_fail_only_derived || []), ...(preview.cross_fail_only_direct || []), ...(preview.cross_fail_both_low_support || [])];
  const rejected = [...(preview.rejected_regions || []), ...(preview.rejected_circuits || []), ...(preview.rejected_connections || [])];
  const set = (id, value) => { if (qs(id)) qs(id).textContent = String(value); };
  const fp = state.fileCenter.preview || {};
  set("count-excel", Number(fp.total_rows || fp.total_lines || state.fileCenter.stats.total || 0));
  set("count-regions", (preview.major_regions || []).length);
  set("count-circuits", (preview.major_circuits || []).length);
  set("count-cross-pass", (preview.cross_pass_connections || []).length);
  set("count-cross-fail", crossFail.length);
  set("count-rejected", rejected.length);
  set("count-report-crosscheck", Number(reports.crosscheck?.cross_pass_records || 0) + Number(reports.crosscheck?.cross_fail_only_derived_records || 0) + Number(reports.crosscheck?.cross_fail_only_direct_records || 0) + Number(reports.crosscheck?.cross_fail_both_low_support_records || 0));
  set("count-report-coverage", reports.coverage?.coverage ? Object.keys(reports.coverage.coverage).length : 0);
  set("count-report-mismatch", (reports.mismatch?.out_of_catalog_region_ids || []).length + (reports.mismatch?.uncovered_regions || []).length);
  set("count-files", Number(state.fileCenter.stats.total || 0));
  set("count-validation", Number(state.fileCenter.stats.validated || 0));
}

async function refreshStatus() {
  const data = await fetchJson("/api/status");
  const cfg = data.config || {};
  const db = cfg.database || {};
  const ds = cfg.deepseek || {};
  const excel = cfg.excel || {};
  const ontology = cfg.ontology || {};
  const pipeline = cfg.pipeline || {};
  const ui = cfg.ui || {};

  qs("db-host").value = db.host || "localhost";
  qs("db-port").value = db.port || 5432;
  qs("db-name").value = db.database || "neurographiq_kg_v2";
  qs("db-user").value = db.user || "postgres";
  qs("db-password").value = db.password === SECRET_MASK ? SECRET_MASK : "";
  qs("db-schema").value = db.schema || "neurokg";

  qs("ds-api-key").value = ds.api_key === SECRET_MASK ? SECRET_MASK : "";
  qs("ds-base-url").value = ds.base_url || "https://api.deepseek.com";
  qs("ds-model").value = ds.model || "deepseek-chat";

  qs("excel-path").value = excel.path || "";
  qs("excel-sheet-index").value = excel.sheet_index || 1;
  qs("excel-header-row").value = excel.header_row || 1;
  qs("ontology-path").value = ontology.path || "";
  qs("pipeline-use-deepseek").checked = Boolean(pipeline.use_deepseek);
  qs("pipeline-batch-size").value = pipeline.batch_size || 60;
  if (qs("ui-language")) qs("ui-language").value = ui.language || state.lang;

  if (qs("db-status")) {
    qs("db-status").textContent = `${t("status_db_prefix")}: ${data.database?.connected ? t("status_connected") : t("status_disconnected")}`;
  }
}

function collectConfigPayload() {
  const payload = {
    database: {
      host: qs("db-host").value.trim() || "localhost",
      port: Number(qs("db-port").value || 5432),
      database: qs("db-name").value.trim() || "neurographiq_kg_v2",
      user: qs("db-user").value.trim() || "postgres",
      schema: qs("db-schema").value.trim() || "neurokg",
    },
    deepseek: {
      base_url: qs("ds-base-url").value.trim() || "https://api.deepseek.com",
      model: qs("ds-model").value.trim() || "deepseek-chat",
    },
    excel: {
      path: qs("excel-path").value.trim(),
      sheet_index: Number(qs("excel-sheet-index").value || 1),
      header_row: Number(qs("excel-header-row").value || 1),
    },
    ontology: { path: qs("ontology-path").value.trim() },
    pipeline: {
      use_deepseek: qs("pipeline-use-deepseek").checked,
      batch_size: Number(qs("pipeline-batch-size").value || 60),
      load_scope: "all_mappable",
    },
    ui: { language: qs("ui-language")?.value || state.lang || "zh" },
  };
  const dbPwd = qs("db-password").value.trim();
  const dsKey = qs("ds-api-key").value.trim();
  if (dbPwd && dbPwd !== SECRET_MASK) payload.database.password = dbPwd;
  if (dsKey && dsKey !== SECRET_MASK) payload.deepseek.api_key = dsKey;
  return payload;
}

async function saveSettings() {
  await fetchJson("/api/config", { method: "POST", body: JSON.stringify(collectConfigPayload()) });
  applyLanguage(qs("ui-language")?.value || state.lang);
  await refreshStatus();
}

async function loadFileList() {
  const data = await fetchJson("/api/files/list");
  state.fileCenter.files = Array.isArray(data.files) ? data.files : [];
  state.fileCenter.stats = data.stats || {};
  state.fileCenter.activeFileId = activeFileId();
  updateCounts();
}

async function loadFileReport(fileId) {
  if (!fileId) return null;
  const report = await fetchJson(`/api/files/${encodeURIComponent(fileId)}/report`);
  state.fileCenter.reports[fileId] = report;
  return report;
}

async function loadFilePreview(fileId, opts = {}) {
  if (!fileId) {
    state.fileCenter.preview = null;
    return null;
  }
  const page = Math.max(1, Number(opts.page || state.fileCenter.previewPage || 1));
  const pageSize = Math.max(1, Number(opts.pageSize || state.fileCenter.previewPageSize || 500));
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize), view: "auto" }).toString();
  const preview = await fetchJson(`/api/files/${encodeURIComponent(fileId)}/preview?${query}`);
  state.fileCenter.preview = preview;
  state.fileCenter.previewPage = Number(preview.page || page);
  state.fileCenter.previewPageSize = pageSize;
  updateCounts();
  return preview;
}

async function ensureActiveFileAssets() {
  const fileId = activeFileId();
  if (!fileId) return;
  state.fileCenter.activeFileId = fileId;
  if (!state.fileCenter.reports[fileId]) await loadFileReport(fileId);
  await loadFilePreview(fileId);
}

function currentPanePayload() {
  const preview = state.latestPreviewBundle?.preview || {};
  const reports = state.latestPreviewBundle?.reports || {};

  if (state.selectedMajorPane === "file_preview") {
    const fp = state.fileCenter.preview || {};
    if (!fp.mode) return { mode: "pre", value: { hint: t("msg_validation_center_hint") }, meta: "" };
    const metaParts = [];
    if (fp.file_type) metaParts.push(`type=${fp.file_type}`);
    if (typeof fp.total_rows === "number") metaParts.push(`rows=${fp.total_rows}`);
    if (typeof fp.total_lines === "number") metaParts.push(`lines=${fp.total_lines}`);
    if (typeof fp.page === "number" && typeof fp.total_pages === "number") metaParts.push(`page=${fp.page}/${fp.total_pages}`);
    metaParts.push(t("msg_preview_page_hint"));
    if (fp.mode === "table") return { mode: "table", rows: fp.rows || [], keys: fp.headers || [], meta: metaParts.join(" | ") };
    if (fp.mode === "raw_embed") return { mode: "embed", value: fp.content_url || "", meta: metaParts.join(" | ") };
    if (fp.mode === "json") return { mode: "pre", value: fp.value || {}, meta: metaParts.join(" | ") };
    return { mode: "pre", value: fp.text || fp, meta: metaParts.join(" | ") };
  }

  if (state.selectedMajorPane === "files_list") {
    const rows = (state.fileCenter.files || []).map((f) => ({
      file_id: f.file_id,
      file_type: f.file_type,
      filename: f.filename,
      overall_label: f.overall_label || "",
      score: f.score ?? "",
      blocked_on_load: Boolean(f.blocked_on_load),
      auto_applied_count: f.auto_applied_count ?? 0,
      manual_required_count: f.manual_required_count ?? 0,
    }));
    return {
      mode: "table",
      rows,
      keys: ["file_id", "file_type", "filename", "overall_label", "score", "blocked_on_load", "auto_applied_count", "manual_required_count"],
      rowKey: "file_id",
      selectedRowKey: activeFileId(),
      meta: `total=${state.fileCenter.stats.total || 0} | pass=${state.fileCenter.stats.pass || 0} | warn=${state.fileCenter.stats.warn || 0} | fail=${state.fileCenter.stats.fail || 0}`,
    };
  }

  if (state.selectedMajorPane === "validation_center") {
    const fileId = activeFileId();
    const bundle = state.fileCenter.reports[fileId];
    if (!bundle) return { mode: "pre", value: { hint: t("msg_validation_center_hint"), active_file_id: fileId }, meta: "" };
    return {
      mode: "pre",
      value: {
        file: bundle.file || {},
        summary: {
          [t("msg_validation_center_label")]: bundle.report?.overall_label || "",
          score: bundle.report?.score ?? "",
          blocked_on_load: Boolean(bundle.report?.blocked_on_load),
          summary_cn: bundle.report?.summary_cn || "",
        },
        [t("msg_validation_center_plan")]: {
          auto_fix_plan: bundle.report?.auto_fix_plan || [],
          manual_fix_plan: bundle.report?.manual_fix_plan || [],
          normalized_change_log: bundle.report?.normalized_change_log || [],
        },
        [t("msg_validation_center_gate")]: bundle.report?.gate_decision || {},
        issues: bundle.report?.issues || [],
      },
      meta: `file_id=${fileId}`,
    };
  }

  if (state.selectedMajorPane === "major_regions") return { mode: "table", rows: preview.major_regions || [], keys: ["major_region_id", "en_name", "cn_name", "laterality"], meta: "" };
  if (state.selectedMajorPane === "major_circuits") return { mode: "table", rows: preview.major_circuits || [], keys: ["major_circuit_id", "circuit_family", "en_name", "circuit_kind", "loop_semantics", "compressed", "confidence_circuit"], meta: "" };
  if (state.selectedMajorPane === "cross_pass") return { mode: "table", rows: preview.cross_pass_connections || [], keys: ["major_connection_id", "source_major_region_id", "target_major_region_id", "relation_type", "connection_modality", "extraction_method"], meta: "" };
  if (state.selectedMajorPane === "cross_fail") return { mode: "table", rows: [...(preview.cross_fail_only_derived || []), ...(preview.cross_fail_only_direct || []), ...(preview.cross_fail_both_low_support || [])], keys: ["major_connection_id", "source_major_region_id", "target_major_region_id", "relation_type", "crosscheck_bucket", "extraction_method"], meta: "" };
  if (state.selectedMajorPane === "rejected") return { mode: "table", rows: [...(preview.rejected_regions || []), ...(preview.rejected_circuits || []), ...(preview.rejected_connections || [])], keys: ["errors", "major_region_id", "major_connection_id", "major_circuit_id"], meta: "" };
  if (state.selectedMajorPane === "report_crosscheck") return { mode: "pre", value: reports.crosscheck || {}, meta: "" };
  if (state.selectedMajorPane === "report_coverage") return { mode: "pre", value: reports.coverage || {}, meta: "" };
  if (state.selectedMajorPane === "report_mismatch") return { mode: "pre", value: reports.mismatch || {}, meta: "" };
  return { mode: "table", rows: [], keys: [], meta: "" };
}

function renderSelectedMajorPane() {
  if (!MAJOR_PANES.includes(state.selectedMajorPane)) state.selectedMajorPane = "file_preview";
  document.querySelectorAll(".major-pane-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.pane === state.selectedMajorPane));
  const titleKey = panelTitleKey(state.selectedMajorPane);
  if (qs("major-pane-title")) {
    qs("major-pane-title").dataset.i18n = titleKey;
    qs("major-pane-title").textContent = t(titleKey);
  }
  const payload = currentPanePayload();
  if (qs("major-pane-meta")) qs("major-pane-meta").textContent = payload.meta || `${t("msg_selected_pane")}: ${t(titleKey)}`;

  const tableWrap = qs("major-pane-table-wrap");
  const preNode = qs("major-pane-pre");
  const embedWrap = qs("major-pane-embed-wrap");
  const embedNode = qs("major-pane-embed");

  if (!tableWrap || !preNode || !embedWrap || !embedNode) {
    appendLog("ui_warning: major pane container missing in DOM, skip renderSelectedMajorPane.");
    return;
  }

  tableWrap.classList.add("hidden");
  preNode.classList.add("hidden");
  embedWrap.classList.add("hidden");
  embedNode.src = "about:blank";

  if (payload.mode === "embed") {
    embedWrap.classList.remove("hidden");
    embedNode.src = payload.value || "about:blank";
    return;
  }
  if (payload.mode === "pre") {
    preNode.classList.remove("hidden");
    renderPre("major-pane-pre", payload.value || {});
    return;
  }
  tableWrap.classList.remove("hidden");
  const tableOpts = {};
  if (state.selectedMajorPane === "files_list") {
    tableOpts.rowKey = payload.rowKey;
    tableOpts.selectedRowKey = payload.selectedRowKey;
    tableOpts.onRowClick = async (fileId) => {
      state.fileCenter.activeFileId = fileId;
      state.fileCenter.previewPage = 1;
      await ensureActiveFileAssets();
      state.selectedMajorPane = "file_preview";
      renderSelectedMajorPane();
    };
  }
  renderTable("major-pane-table", payload.rows || [], payload.keys || [], tableOpts);
}

async function selectMajorPane(pane) {
  state.selectedMajorPane = pane;
  if (pane === "file_preview" || pane === "validation_center") await ensureActiveFileAssets();
  renderSelectedMajorPane();
}

async function validateAndAutoFixFile(file) {
  if (!file?.file_id) return null;
  appendLog(`${t("msg_file_validate_started")}: ${file.filename}`);
  try {
    const validated = await fetchJson("/api/files/validate", {
      method: "POST",
      body: JSON.stringify({ file_id: file.file_id, runtime_overrides: collectConfigPayload() }),
    });
    const report = validated.validation_report || {};
    appendLog(`${t("msg_file_validate_done")}: ${file.filename} | label=${report.overall_label || "-"} | score=${report.score ?? "-"}`);
    const fixed = await fetchJson("/api/files/apply-auto-fix", {
      method: "POST",
      body: JSON.stringify({ file_id: file.file_id }),
    });
    appendLog(`${t("msg_file_auto_fix_done")}: ${file.filename} | auto_applied=${fixed.auto_applied_count || 0}`);
    if (report.blocked_on_load) appendLog(`${t("msg_file_blocked_on_load")}: ${file.filename}`);
    await loadFileReport(file.file_id);
    return report;
  } catch (err) {
    appendLog(`${t("msg_file_validate_error")}: ${file.filename} | ${String(err)}`);
    return null;
  }
}

async function validateAndAutoFixAllFiles() {
  await loadFileList();
  for (const file of state.fileCenter.files || []) {
    await validateAndAutoFixFile(file);
  }
  await loadFileList();
  appendLog(`${t("msg_file_list_loaded")}: total=${state.fileCenter.stats.total || 0} pass=${state.fileCenter.stats.pass || 0} warn=${state.fileCenter.stats.warn || 0} fail=${state.fileCenter.stats.fail || 0}`);
}

async function uploadManagedFiles(files) {
  const uploaded = [];
  for (const file of files) {
    const result = await uploadFile(file);
    const rec = result.file || {};
    uploaded.push(rec);
    appendLog(`${t("msg_file_uploaded")}: ${rec.filename || file.name} (${rec.file_type || "-"})`);
    if (["xlsx", "csv", "tsv", "json", "jsonl"].includes(rec.file_type)) {
      qs("excel-path").value = rec.original_path || "";
      state.fileCenter.activeFileId = rec.file_id || "";
    }
    if (["rdf", "owl", "xml"].includes(rec.file_type)) {
      qs("ontology-path").value = rec.original_path || "";
    }
  }
  appendLog(`${t("msg_uploaded_count")}: ${uploaded.length}`);
  await saveSettings();
  await loadFileList();
  for (const rec of uploaded) await validateAndAutoFixFile(rec);
  await loadFileList();
  await ensureActiveFileAssets();
}

function startPolling(jobId, onDone) {
  if (state.pollingTimer) clearInterval(state.pollingTimer);
  state.currentJobId = jobId;
  state.pollingTimer = setInterval(async () => {
    try {
      const job = await fetchJson(`/api/jobs/${jobId}`);
      updateJobUi(job);
      if (job.status === "succeeded" || job.status === "failed") {
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
        if (onDone) onDone(job);
      }
    } catch (err) {
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
      appendLog(`polling_error: ${String(err)}`);
    }
  }, 1500);
}

async function runSchemaRebuild() {
  const data = await fetchJson("/api/schema/rebuild", { method: "POST" });
  startPolling(data.job_id, async () => refreshStatus());
}

async function runMajorPreview() {
  const payload = {
    excel_path: qs("excel-path").value.trim(),
    runtime_overrides: collectConfigPayload(),
    save_runtime_overrides: true,
  };
  let data;
  const response = await fetch("/api/extract/major/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let parsed = {};
  try {
    parsed = await response.json();
  } catch {}
  if (response.status === 404) {
    data = await fetchJson("/api/preview/major", { method: "POST", body: JSON.stringify(payload) });
  } else if (!response.ok) {
    throw new Error(parsed.message || parsed.error || `Request failed: ${response.status}`);
  } else {
    data = parsed;
  }

  state.currentPreviewJobId = data.job_id;
  appendLog(`run_id=${data.run_id || "-"} | endpoint=${data.endpoint || "/api/preview/major"} | use_deepseek_effective=${data.use_deepseek_effective}`);
  startPolling(data.job_id, async (job) => {
    if (job.status !== "succeeded") return;
    state.latestPreviewBundle = await fetchJson(`/api/jobs/${data.job_id}/preview`);
    updateCounts();
    renderPre("anatomy-summary", state.latestPreviewBundle.summary || {});
    await selectMajorPane("major_regions");
    switchModule("module-major");
  });
}

async function runLoadToDb() {
  if (!state.currentPreviewJobId) throw new Error(t("msg_run_preview_first"));
  try {
    const data = await fetchJson(`/api/jobs/${state.currentPreviewJobId}/load`, { method: "POST" });
    startPolling(data.job_id);
  } catch (err) {
    if (err.payload?.error === "load_blocked_by_validation") {
      const blocked = Array.isArray(err.payload.blocked_files) ? err.payload.blocked_files : [];
      appendLog(`${t("msg_load_blocked_validation")} (${blocked.length})`);
      blocked.forEach((row) => appendLog(`- ${row.file_id || "-"} | ${row.filename || "-"} | ${row.overall_label || "FAIL"}`));
      await loadFileList();
      await selectMajorPane("files_list");
    }
    throw err;
  }
}

async function openReports() {
  const reportsPath = state.latestPreviewBundle?.summary?.paths?.reports;
  if (!reportsPath) throw new Error(t("msg_run_preview_for_reports"));
  renderPre("job-logs", `${t("msg_reports_path")}:\n${reportsPath}`);
}

async function startExtraction() {
  await saveSettings();
  await validateAndAutoFixAllFiles();
  const inputPath = String(qs("excel-path").value || "").trim();
  if (!inputPath || !STRUCTURED_EXT.has(extOf(inputPath))) throw new Error(t("msg_unstructured_extract_block"));
  await ensureActiveFileAssets();
  await runMajorPreview();
}

function bindEvents() {
  document.querySelectorAll(".module-btn").forEach((btn) => btn.addEventListener("click", () => switchModule(btn.dataset.module)));
  document.querySelectorAll(".major-pane-btn").forEach((btn) => btn.addEventListener("click", () => { void selectMajorPane(btn.dataset.pane); }));
  qs("ui-language")?.addEventListener("change", (event) => applyLanguage(event.target.value));

  qs("btn-save-config")?.addEventListener("click", async () => {
    try { await saveSettings(); } catch (err) { renderPre("job-logs", `${t("msg_save_settings_error")}: ${String(err)}`); }
  });
  qs("btn-import-excel")?.addEventListener("click", () => qs("input-upload-excel").click());
  qs("btn-import-ontology")?.addEventListener("click", () => qs("input-upload-ontology").click());

  qs("input-upload-excel")?.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      await uploadManagedFiles(files);
      await selectMajorPane("file_preview");
      switchModule("module-major");
    } catch (err) {
      renderPre("job-logs", `${t("msg_excel_import_error")}: ${String(err)}`);
    } finally {
      event.target.value = "";
    }
  });

  qs("input-upload-ontology")?.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      await uploadManagedFiles(files);
      await selectMajorPane("files_list");
      switchModule("module-major");
    } catch (err) {
      renderPre("job-logs", `${t("msg_ontology_import_error")}: ${String(err)}`);
    } finally {
      event.target.value = "";
    }
  });

  qs("btn-rebuild-schema")?.addEventListener("click", async () => {
    try { await saveSettings(); await runSchemaRebuild(); } catch (err) { renderPre("job-logs", `${t("msg_schema_rebuild_error")}: ${String(err)}`); }
  });
  qs("btn-start-extract")?.addEventListener("click", async () => {
    try { await startExtraction(); } catch (err) { renderPre("job-logs", `${t("msg_preview_run_error")}: ${String(err)}`); }
  });
  qs("btn-load-db")?.addEventListener("click", async () => {
    try { await runLoadToDb(); } catch (err) { renderPre("job-logs", `${t("msg_load_error")}: ${String(err)}`); }
  });
  qs("btn-open-reports")?.addEventListener("click", async () => {
    try { await openReports(); } catch (err) { renderPre("job-logs", `${t("msg_open_reports_error")}: ${String(err)}`); }
  });

  document.addEventListener("keydown", async (event) => {
    if (state.selectedMajorPane !== "file_preview") return;
    const fileId = activeFileId();
    if (!fileId) return;
    const p = state.fileCenter.preview || {};
    const page = Number(p.page || 1);
    const total = Number(p.total_pages || 1);
    if (event.key === "," && page > 1) {
      event.preventDefault();
      await loadFilePreview(fileId, { page: page - 1 });
      renderSelectedMajorPane();
    }
    if (event.key === "." && page < total) {
      event.preventDefault();
      await loadFilePreview(fileId, { page: page + 1 });
      renderSelectedMajorPane();
    }
  });
}

async function bootstrap() {
  bindEvents();
  applyLanguage(localStorage.getItem("ui_lang") || "zh");
  try {
    await refreshStatus();
    await loadFileList();
    await ensureActiveFileAssets();
  } catch (err) {
    appendLog(`bootstrap_error: ${String(err)}`);
  }
  updateCounts();
  renderSelectedMajorPane();
}

bootstrap();
