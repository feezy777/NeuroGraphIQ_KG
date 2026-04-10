const state = {
  activeTab: "tab-files",
  files: [],
  selectedFileId: "",
  selectedBundle: null,
  candidates: [],
  selectedCandidateId: "",
  circuitCandidates: [],
  selectedCircuitCandidateId: "",
  connectionCandidates: [],
  selectedConnectionCandidateId: "",
  tasks: [],
  logs: [],
  runtime: null,
  lastExtractSummary: {},
  lastCircuitExtractSummary: {},
  lastConnectionExtractSummary: {},
  lastCommitResult: {},
  lastCircuitCommitResult: {},
  lastConnectionCommitResult: {},
  unverifiedRegions: [],
  selectedUnverifiedId: "",
  unverifiedCircuits: [],
  selectedUnverifiedCircuitId: "",
  unverifiedConnections: [],
  selectedUnverifiedConnectionId: "",
};

function qs(id) {
  return document.getElementById(id);
}

async function api(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { ok: false, error: text };
  }
  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || `HTTP_${resp.status}`);
  }
  return data;
}

function setActiveTab(tabId) {
  state.activeTab = tabId;
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.toggle("active", el.id === tabId));
  document.querySelectorAll(".tab-btn").forEach((el) => el.classList.toggle("active", el.dataset.tab === tabId));
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.tab === tabId));
}

function pretty(obj) {
  return JSON.stringify(obj || {}, null, 2);
}

function appendClientLog(message, level = "info") {
  state.logs.push({
    created_at: new Date().toISOString(),
    module: "UI",
    level,
    message,
  });
  renderConsole();
}

function renderConsole() {
  const el = qs("console-content");
  if (!el) return;
  const rows = [...state.logs].slice(-220).map((it) => `[${it.created_at || "-"}] [${it.module || "APP"}] ${it.message || ""}`);
  el.textContent = rows.join("\n");
}

function fileActionButtons(file) {
  return `
    <button class="btn mini" data-action="reparse" data-file-id="${file.file_id}">閲嶆柊瑙ｆ瀽</button>
    <button class="btn mini" data-action="extract" data-file-id="${file.file_id}">鎶藉彇鑴戝尯</button>
    <button class="btn mini" data-action="remove" data-file-id="${file.file_id}">绉婚櫎</button>
  `;
}

function renderFileTable() {
  const tbody = document.querySelector("#file-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.files.forEach((file) => {
    const tr = document.createElement("tr");
    tr.className = file.file_id === state.selectedFileId ? "is-selected" : "";
    tr.dataset.fileId = file.file_id;
    tr.innerHTML = `
      <td>${file.filename || "-"}</td>
      <td>${file.file_type || "-"}</td>
      <td>${file.size_bytes || 0}</td>
      <td>${file.status || "-"}</td>
      <td>${fileActionButtons(file)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderFileDetail() {
  const bundle = state.selectedBundle || {};
  const file = bundle.file || {};
  const parsed = bundle.parsed || {};
  const doc = parsed.document || {};

  qs("file-meta-id").textContent = file.file_id || "-";
  qs("file-meta-type").textContent = file.file_type || "-";
  qs("file-meta-status").textContent = file.status || "-";
  qs("file-meta-parse-task").textContent = file.latest_parse_task_id || "-";

  const previewText = doc.raw_text || (parsed.chunks || []).map((it) => it.text_content || "").join("\n").slice(0, 5000);
  qs("file-preview-content").textContent = previewText || "鏆傛棤棰勮";
  qs("file-normalized-content").textContent = pretty(bundle.normalized || {});
}

function renderExtractionSummary() {
  qs("extract-summary").textContent = pretty(state.lastExtractSummary || {});
}

function renderCircuitExtractionSummary() {
  qs("circuit-extract-summary").textContent = pretty(state.lastCircuitExtractSummary || {});
}

function renderConnectionExtractionSummary() {
  qs("connection-extract-summary").textContent = pretty(state.lastConnectionExtractSummary || {});
}

function renderCandidateTable() {
  const tbody = document.querySelector("#candidate-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const uvByCandidate = new Map((state.unverifiedRegions || []).map((row) => [row.source_candidate_region_id, row]));
  state.candidates.forEach((it) => {
    const uv = uvByCandidate.get(it.id);
    const tr = document.createElement("tr");
    tr.className = it.id === state.selectedCandidateId ? "is-selected" : "";
    tr.dataset.candidateId = it.id;
    const errorSummary = uv ? (uv.latest_promotion_message || uv.latest_validation_message || "-") : "-";
    tr.innerHTML = `
      <td>${it.id || "-"}</td>
      <td>${it.en_name_candidate || "-"}</td>
      <td>${it.cn_name_candidate || "-"}</td>
      <td>${it.granularity_candidate || "-"}</td>
      <td>${it.confidence ?? "-"}</td>
      <td>${it.status || "-"}</td>
      <td>${uv ? uv.id : "-"}</td>
      <td>${uv ? (uv.validation_status || "-") : "-"}</td>
      <td>${uv ? (uv.promotion_status || "-") : "-"}</td>
      <td>${errorSummary}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderCircuitCandidateTable() {
  const tbody = document.querySelector("#circuit-candidate-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const uvByCandidate = new Map((state.unverifiedCircuits || []).map((row) => [row.source_candidate_circuit_id, row]));
  state.circuitCandidates.forEach((it) => {
    const uv = uvByCandidate.get(it.id);
    const nodes = Array.isArray(it.nodes) ? it.nodes : [];
    const tr = document.createElement("tr");
    tr.className = it.id === state.selectedCircuitCandidateId ? "is-selected" : "";
    tr.dataset.circuitCandidateId = it.id;
    const errorSummary = uv ? (uv.latest_promotion_message || uv.latest_validation_message || "-") : "-";
    tr.innerHTML = `
      <td>${it.id || "-"}</td>
      <td>${it.en_name_candidate || "-"}</td>
      <td>${it.cn_name_candidate || "-"}</td>
      <td>${it.granularity_candidate || "-"}</td>
      <td>${it.circuit_kind_candidate || "-"}</td>
      <td>${it.loop_type_candidate || "-"}</td>
      <td>${nodes.length}</td>
      <td>${it.status || "-"}</td>
      <td>${uv ? uv.id : "-"}</td>
      <td>${uv ? (uv.validation_status || "-") : "-"}</td>
      <td>${uv ? (uv.promotion_status || "-") : "-"}</td>
      <td>${errorSummary}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderConnectionCandidateTable() {
  const tbody = document.querySelector("#connection-candidate-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const uvByCandidate = new Map((state.unverifiedConnections || []).map((row) => [row.source_candidate_connection_id, row]));
  state.connectionCandidates.forEach((it) => {
    const uv = uvByCandidate.get(it.id);
    const tr = document.createElement("tr");
    tr.className = it.id === state.selectedConnectionCandidateId ? "is-selected" : "";
    tr.dataset.connectionCandidateId = it.id;
    const errorSummary = uv ? (uv.latest_promotion_message || uv.latest_validation_message || "-") : "-";
    tr.innerHTML = `
      <td>${it.id || "-"}</td>
      <td>${it.en_name_candidate || "-"}</td>
      <td>${it.cn_name_candidate || "-"}</td>
      <td>${it.granularity_candidate || "-"}</td>
      <td>${it.connection_modality_candidate || "-"}</td>
      <td>${it.source_region_ref_candidate || "-"}</td>
      <td>${it.target_region_ref_candidate || "-"}</td>
      <td>${it.status || "-"}</td>
      <td>${uv ? uv.id : "-"}</td>
      <td>${uv ? (uv.validation_status || "-") : "-"}</td>
      <td>${uv ? (uv.promotion_status || "-") : "-"}</td>
      <td>${errorSummary}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderInspector() {
  const el = qs("inspector-content");
  if (!el) return;
  const selectedCandidate = state.candidates.find((it) => it.id === state.selectedCandidateId) || null;
  const selectedCircuitCandidate = state.circuitCandidates.find((it) => it.id === state.selectedCircuitCandidateId) || null;
  const selectedConnectionCandidate = state.connectionCandidates.find((it) => it.id === state.selectedConnectionCandidateId) || null;
  const selectedUnverified = state.unverifiedRegions.find((it) => it.id === state.selectedUnverifiedId) || null;
  const selectedUnverifiedCircuit = state.unverifiedCircuits.find((it) => it.id === state.selectedUnverifiedCircuitId) || null;
  const selectedUnverifiedConnection = state.unverifiedConnections.find((it) => it.id === state.selectedUnverifiedConnectionId) || null;
  el.textContent = pretty({
    file: state.selectedBundle ? state.selectedBundle.file : null,
    selected_candidate: selectedCandidate,
    selected_circuit_candidate: selectedCircuitCandidate,
    selected_connection_candidate: selectedConnectionCandidate,
    selected_unverified: selectedUnverified,
    selected_unverified_circuit: selectedUnverifiedCircuit,
    selected_unverified_connection: selectedUnverifiedConnection,
    deepseek_enabled: !!state.runtime?.deepseek?.enabled,
  });
}

function fillCandidateEditor(candidate) {
  if (!candidate) {
    qs("review-id").value = "";
    qs("review-en").value = "";
    qs("review-cn").value = "";
    qs("review-alias").value = "";
    qs("review-laterality").value = "unknown";
    qs("review-granularity").value = "unknown";
    qs("review-region-category").value = "";
    qs("review-ontology-source").value = "";
    qs("review-parent").value = "";
    qs("review-confidence").value = "";
    qs("review-note").value = "";
    return;
  }
  qs("review-id").value = candidate.id || "";
  qs("review-en").value = candidate.en_name_candidate || "";
  qs("review-cn").value = candidate.cn_name_candidate || "";
  qs("review-alias").value = (candidate.alias_candidates || []).join(", ");
  qs("review-laterality").value = candidate.laterality_candidate || "unknown";
  qs("review-granularity").value = candidate.granularity_candidate || "unknown";
  qs("review-region-category").value = candidate.region_category_candidate || "";
  qs("review-ontology-source").value = candidate.ontology_source_candidate || "";
  qs("review-parent").value = candidate.parent_region_candidate || "";
  qs("review-confidence").value = candidate.confidence ?? "";
  qs("review-note").value = candidate.review_note || "";
}

function fillCircuitEditor(candidate) {
  if (!candidate) {
    qs("c-review-id").value = "";
    qs("c-review-en").value = "";
    qs("c-review-cn").value = "";
    qs("c-review-alias").value = "";
    qs("c-review-description").value = "";
    qs("c-review-granularity").value = "unknown";
    qs("c-review-kind").value = "unknown";
    qs("c-review-loop-type").value = "inferred";
    qs("c-review-cycle-verified").checked = false;
    qs("c-review-confidence").value = "";
    qs("c-review-note").value = "";
    qs("c-review-nodes").value = "[]";
    return;
  }
  qs("c-review-id").value = candidate.id || "";
  qs("c-review-en").value = candidate.en_name_candidate || "";
  qs("c-review-cn").value = candidate.cn_name_candidate || "";
  qs("c-review-alias").value = (candidate.alias_candidates || []).join(", ");
  qs("c-review-description").value = candidate.description_candidate || "";
  qs("c-review-granularity").value = candidate.granularity_candidate || "unknown";
  qs("c-review-kind").value = candidate.circuit_kind_candidate || "unknown";
  qs("c-review-loop-type").value = candidate.loop_type_candidate || "inferred";
  qs("c-review-cycle-verified").checked = !!candidate.cycle_verified_candidate;
  qs("c-review-confidence").value = candidate.confidence_circuit ?? "";
  qs("c-review-note").value = candidate.review_note || "";
  qs("c-review-nodes").value = pretty(candidate.nodes || []);
}

function fillConnectionEditor(candidate) {
  if (!candidate) {
    qs("conn-review-id").value = "";
    qs("conn-review-en").value = "";
    qs("conn-review-cn").value = "";
    qs("conn-review-alias").value = "";
    qs("conn-review-description").value = "";
    qs("conn-review-granularity").value = "unknown";
    qs("conn-review-modality").value = "unknown";
    qs("conn-review-source").value = "";
    qs("conn-review-target").value = "";
    qs("conn-review-direction").value = "unknown";
    qs("conn-review-confidence").value = "";
    qs("conn-review-note").value = "";
    return;
  }
  qs("conn-review-id").value = candidate.id || "";
  qs("conn-review-en").value = candidate.en_name_candidate || "";
  qs("conn-review-cn").value = candidate.cn_name_candidate || "";
  qs("conn-review-alias").value = (candidate.alias_candidates || []).join(", ");
  qs("conn-review-description").value = candidate.description_candidate || "";
  qs("conn-review-granularity").value = candidate.granularity_candidate || "unknown";
  qs("conn-review-modality").value = candidate.connection_modality_candidate || "unknown";
  qs("conn-review-source").value = candidate.source_region_ref_candidate || "";
  qs("conn-review-target").value = candidate.target_region_ref_candidate || "";
  qs("conn-review-direction").value = candidate.direction_label || "unknown";
  qs("conn-review-confidence").value = candidate.confidence ?? "";
  qs("conn-review-note").value = candidate.review_note || "";
}

function syncConfigPanel(runtime) {
  state.runtime = runtime;
  qs("cfg-deepseek-enabled").checked = !!runtime?.deepseek?.enabled;
  qs("cfg-deepseek-key").value = runtime?.deepseek?.api_key || "";
  qs("cfg-deepseek-base").value = runtime?.deepseek?.base_url || "";
  qs("cfg-deepseek-model").value = runtime?.deepseek?.model || "";
  qs("cfg-deepseek-temperature").value = runtime?.deepseek?.temperature ?? 0.2;
  qs("cfg-normalize-mode").value = runtime?.pipeline?.normalize_mode_default || "local";
  qs("cfg-validate-mode").value = runtime?.pipeline?.validate_mode_default || "local";
}

function syncExtractSelectors() {
  const select = qs("extract-file-select");
  const circuitSelect = qs("circuit-extract-file-select");
  const connectionSelect = qs("connection-extract-file-select");
  select.innerHTML = "";
  circuitSelect.innerHTML = "";
  connectionSelect.innerHTML = "";
  state.files.forEach((f) => {
    const opt = document.createElement("option");
    opt.value = f.file_id;
    opt.textContent = `${f.filename} (${f.file_type})`;
    select.appendChild(opt);

    const opt2 = document.createElement("option");
    opt2.value = f.file_id;
    opt2.textContent = `${f.filename} (${f.file_type})`;
    circuitSelect.appendChild(opt2);

    const opt3 = document.createElement("option");
    opt3.value = f.file_id;
    opt3.textContent = `${f.filename} (${f.file_type})`;
    connectionSelect.appendChild(opt3);
  });
  if (state.selectedFileId) {
    select.value = state.selectedFileId;
    circuitSelect.value = state.selectedFileId;
    connectionSelect.value = state.selectedFileId;
  }
}

function renderTasks() {
  const tbody = document.querySelector("#task-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.tasks.forEach((task) => {
    const tr = document.createElement("tr");
    tr.dataset.taskId = task.task_id;
    tr.innerHTML = `
      <td>${task.task_id}</td>
      <td>${task.task_type}</td>
      <td>${task.status}</td>
      <td>${task.initiator}</td>
      <td>${task.started_at || "-"}</td>
      <td>${task.ended_at || "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderUnverifiedTable() {
  const tbody = document.querySelector("#unverified-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.unverifiedRegions.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.unverifiedId = row.id;
    tr.className = row.id === state.selectedUnverifiedId ? "is-selected" : "";
    const validationErrors = (row.latest_validation_detail_json && row.latest_validation_detail_json.errors) || [];
    const validationWarnings = (row.latest_validation_detail_json && row.latest_validation_detail_json.warnings) || [];
    const errorSummary =
      row.latest_promotion_message ||
      row.latest_validation_message ||
      (validationErrors.length ? `errors=${validationErrors.join("|")}` : "") ||
      (validationWarnings.length ? `warnings=${validationWarnings.join("|")}` : "") ||
      row.review_note ||
      "-";
    tr.innerHTML = `
      <td>${row.id || "-"}</td>
      <td>${row.source_candidate_region_id || "-"}</td>
      <td>${row.granularity || "-"}</td>
      <td>${row.validation_status || "-"}</td>
      <td>${row.promotion_status || "-"}</td>
      <td>${row.target_table || "-"}</td>
      <td>${row.target_region_id || "-"}</td>
      <td>${row.region_code || "-"}</td>
      <td>${errorSummary}</td>
      <td>${row.confidence ?? "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderUnverifiedCircuitTable() {
  const tbody = document.querySelector("#unverified-circuit-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.unverifiedCircuits.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.unverifiedCircuitId = row.id;
    tr.className = row.id === state.selectedUnverifiedCircuitId ? "is-selected" : "";
    const validationErrors = (row.latest_validation_detail_json && row.latest_validation_detail_json.errors) || [];
    const validationWarnings = (row.latest_validation_detail_json && row.latest_validation_detail_json.warnings) || [];
    const errorSummary =
      row.latest_promotion_message ||
      row.latest_validation_message ||
      (validationErrors.length ? `errors=${validationErrors.join("|")}` : "") ||
      (validationWarnings.length ? `warnings=${validationWarnings.join("|")}` : "") ||
      row.review_note ||
      "-";
    const evidenceSummary = `count=${row.evidence_count ?? (row.evidence_json || []).length ?? 0}`;
    tr.innerHTML = `
      <td>${row.id || "-"}</td>
      <td>${row.source_candidate_circuit_id || "-"}</td>
      <td>${row.granularity || "-"}</td>
      <td>${row.circuit_kind || "-"}</td>
      <td>${row.loop_type || "-"}</td>
      <td>${(row.nodes || []).length}</td>
      <td>${row.validation_status || "-"}</td>
      <td>${row.promotion_status || "-"}</td>
      <td>${evidenceSummary}</td>
      <td>${row.target_table || "-"}</td>
      <td>${row.target_circuit_id || "-"}</td>
      <td>${row.circuit_code || "-"}</td>
      <td>${errorSummary}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderUnverifiedConnectionTable() {
  const tbody = document.querySelector("#unverified-connection-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.unverifiedConnections.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.unverifiedConnectionId = row.id;
    tr.className = row.id === state.selectedUnverifiedConnectionId ? "is-selected" : "";
    const validationErrors = (row.latest_validation_detail_json && row.latest_validation_detail_json.errors) || [];
    const validationWarnings = (row.latest_validation_detail_json && row.latest_validation_detail_json.warnings) || [];
    const errorSummary =
      row.latest_promotion_message ||
      row.latest_validation_message ||
      (validationErrors.length ? `errors=${validationErrors.join("|")}` : "") ||
      (validationWarnings.length ? `warnings=${validationWarnings.join("|")}` : "") ||
      row.review_note ||
      "-";
    const evidenceSummary = `count=${row.evidence_count ?? (row.evidence_json || []).length ?? 0}`;
    tr.innerHTML = `
      <td>${row.id || "-"}</td>
      <td>${row.source_candidate_connection_id || "-"}</td>
      <td>${row.granularity || "-"}</td>
      <td>${row.connection_modality || "-"}</td>
      <td>${row.source_region_ref || "-"}</td>
      <td>${row.target_region_ref || "-"}</td>
      <td>${row.validation_status || "-"}</td>
      <td>${row.promotion_status || "-"}</td>
      <td>${evidenceSummary}</td>
      <td>${row.target_table || "-"}</td>
      <td>${row.target_connection_id || "-"}</td>
      <td>${row.connection_code || "-"}</td>
      <td>${errorSummary}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function refreshStatus() {
  const payload = await api("/api/status");
  syncConfigPanel(payload.status.runtime);
}

async function refreshLogs() {
  const payload = await api("/api/logs?limit=220");
  state.logs = payload.logs || [];
  renderConsole();
}

async function refreshTasks() {
  const payload = await api("/api/runs/list");
  state.tasks = payload.runs || [];
  renderTasks();
}

async function refreshFiles() {
  const payload = await api("/api/files/list");
  state.files = payload.files || [];
  renderFileTable();
  syncExtractSelectors();
  if (!state.selectedFileId && state.files.length > 0) {
    state.selectedFileId = state.files[0].file_id;
  }
}

async function refreshCandidates() {
  if (!state.selectedFileId) {
    state.candidates = [];
    renderCandidateTable();
    fillCandidateEditor(null);
    return;
  }
  const payload = await api(`/api/files/${state.selectedFileId}/region-candidates`);
  state.candidates = payload.items || [];
  if (state.selectedCandidateId && !state.candidates.some((it) => it.id === state.selectedCandidateId)) {
    state.selectedCandidateId = "";
  }
  if (!state.selectedCandidateId && state.candidates.length > 0) {
    state.selectedCandidateId = state.candidates[0].id;
  }
  renderCandidateTable();
  fillCandidateEditor(state.candidates.find((it) => it.id === state.selectedCandidateId));
}

async function refreshCircuitCandidates() {
  if (!state.selectedFileId) {
    state.circuitCandidates = [];
    renderCircuitCandidateTable();
    fillCircuitEditor(null);
    return;
  }
  const payload = await api(`/api/files/${state.selectedFileId}/circuit-candidates`);
  state.circuitCandidates = payload.items || [];
  if (state.selectedCircuitCandidateId && !state.circuitCandidates.some((it) => it.id === state.selectedCircuitCandidateId)) {
    state.selectedCircuitCandidateId = "";
  }
  if (!state.selectedCircuitCandidateId && state.circuitCandidates.length > 0) {
    state.selectedCircuitCandidateId = state.circuitCandidates[0].id;
  }
  renderCircuitCandidateTable();
  fillCircuitEditor(state.circuitCandidates.find((it) => it.id === state.selectedCircuitCandidateId));
}

async function refreshConnectionCandidates() {
  if (!state.selectedFileId) {
    state.connectionCandidates = [];
    renderConnectionCandidateTable();
    fillConnectionEditor(null);
    return;
  }
  const payload = await api(`/api/files/${state.selectedFileId}/connection-candidates`);
  state.connectionCandidates = payload.items || [];
  if (state.selectedConnectionCandidateId && !state.connectionCandidates.some((it) => it.id === state.selectedConnectionCandidateId)) {
    state.selectedConnectionCandidateId = "";
  }
  if (!state.selectedConnectionCandidateId && state.connectionCandidates.length > 0) {
    state.selectedConnectionCandidateId = state.connectionCandidates[0].id;
  }
  renderConnectionCandidateTable();
  fillConnectionEditor(state.connectionCandidates.find((it) => it.id === state.selectedConnectionCandidateId));
}

async function refreshUnverified(sourceFileId = "") {
  const query = sourceFileId ? `?file_id=${encodeURIComponent(sourceFileId)}` : "";
  const payload = await api(`/api/unverified/regions${query}`);
  state.unverifiedRegions = payload.items || [];
  if (state.selectedUnverifiedId && !state.unverifiedRegions.some((it) => it.id === state.selectedUnverifiedId)) {
    state.selectedUnverifiedId = "";
  }
  if (!state.selectedUnverifiedId && state.unverifiedRegions.length > 0) {
    state.selectedUnverifiedId = state.unverifiedRegions[0].id;
  }
  renderUnverifiedTable();
  renderCandidateTable();
}

async function refreshUnverifiedCircuits(sourceFileId = "") {
  const query = sourceFileId ? `?file_id=${encodeURIComponent(sourceFileId)}` : "";
  const payload = await api(`/api/unverified/circuits${query}`);
  state.unverifiedCircuits = payload.items || [];
  if (state.selectedUnverifiedCircuitId && !state.unverifiedCircuits.some((it) => it.id === state.selectedUnverifiedCircuitId)) {
    state.selectedUnverifiedCircuitId = "";
  }
  if (!state.selectedUnverifiedCircuitId && state.unverifiedCircuits.length > 0) {
    state.selectedUnverifiedCircuitId = state.unverifiedCircuits[0].id;
  }
  renderUnverifiedCircuitTable();
  renderCircuitCandidateTable();
}

async function refreshUnverifiedConnections(sourceFileId = "") {
  const query = sourceFileId ? `?file_id=${encodeURIComponent(sourceFileId)}` : "";
  const payload = await api(`/api/unverified/connections${query}`);
  state.unverifiedConnections = payload.items || [];
  if (state.selectedUnverifiedConnectionId && !state.unverifiedConnections.some((it) => it.id === state.selectedUnverifiedConnectionId)) {
    state.selectedUnverifiedConnectionId = "";
  }
  if (!state.selectedUnverifiedConnectionId && state.unverifiedConnections.length > 0) {
    state.selectedUnverifiedConnectionId = state.unverifiedConnections[0].id;
  }
  renderUnverifiedConnectionTable();
  renderConnectionCandidateTable();
}

async function selectFile(fileId) {
  if (!fileId) return;
  state.selectedFileId = fileId;
  renderFileTable();
  const payload = await api(`/api/files/${fileId}`);
  state.selectedBundle = payload.bundle;
  renderFileDetail();
  syncExtractSelectors();
  await refreshCandidates();
  await refreshCircuitCandidates();
  await refreshConnectionCandidates();
  await refreshUnverified(fileId);
  await refreshUnverifiedCircuits(fileId);
  await refreshUnverifiedConnections(fileId);
  renderInspector();
}

async function runFileAction(action, fileId) {
  try {
    if (action === "remove") {
      await api(`/api/files/${fileId}`, { method: "DELETE" });
      appendClientLog(`[FILE] remove success file_id=${fileId}`);
      if (state.selectedFileId === fileId) {
        state.selectedFileId = "";
        state.selectedBundle = null;
        state.selectedCandidateId = "";
      }
    } else if (action === "reparse") {
      await api(`/api/files/${fileId}/reparse`, { method: "POST" });
      appendClientLog(`[PARSING] reparse triggered file_id=${fileId}`);
    } else if (action === "extract") {
      const mode = qs("extract-mode-select").value || "local";
      await api(`/api/files/${fileId}/extract-regions`, { method: "POST", body: JSON.stringify({ mode }) });
      appendClientLog(`[EXTRACT] region_extract triggered file_id=${fileId} mode=${mode}`);
    }
    await bootstrap();
  } catch (err) {
    appendClientLog(`[ERROR] action=${action} file_id=${fileId} reason=${err.message}`, "error");
    alert(`鎿嶄綔澶辫触: ${err.message}`);
  }
}

async function uploadFile(inputEl) {
  const file = inputEl.files && inputEl.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  appendClientLog(`[FILE] upload_start file=${file.name}`);
  const resp = await fetch("/api/files/upload", { method: "POST", body: form });
  const data = await resp.json();
  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || "upload_failed");
  }
  appendClientLog(`[FILE] upload_success file=${file.name}`);
  inputEl.value = "";
  await bootstrap();
}

async function saveConfig() {
  const payload = {
    deepseek: {
      enabled: qs("cfg-deepseek-enabled").checked,
      api_key: qs("cfg-deepseek-key").value,
      base_url: qs("cfg-deepseek-base").value,
      model: qs("cfg-deepseek-model").value,
      temperature: Number(qs("cfg-deepseek-temperature").value || 0.2),
    },
    pipeline: {
      normalize_mode_default: qs("cfg-normalize-mode").value,
      validate_mode_default: qs("cfg-validate-mode").value,
    },
  };
  await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
  appendClientLog("[CONFIG] saved");
}

function currentCandidatePatch() {
  return {
    en_name_candidate: qs("review-en").value.trim(),
    cn_name_candidate: qs("review-cn").value.trim(),
    alias_candidates: qs("review-alias").value.split(",").map((it) => it.trim()).filter(Boolean),
    laterality_candidate: qs("review-laterality").value,
    granularity_candidate: qs("review-granularity").value,
    region_category_candidate: qs("review-region-category").value.trim(),
    ontology_source_candidate: qs("review-ontology-source").value.trim(),
    parent_region_candidate: qs("review-parent").value.trim(),
    confidence: Number(qs("review-confidence").value || 0),
    review_note: qs("review-note").value.trim(),
  };
}

function currentCircuitPatch() {
  let nodes = [];
  const raw = qs("c-review-nodes").value.trim();
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        nodes = parsed;
      }
    } catch {
      throw new Error("invalid_nodes_json");
    }
  }
  return {
    en_name_candidate: qs("c-review-en").value.trim(),
    cn_name_candidate: qs("c-review-cn").value.trim(),
    alias_candidates: qs("c-review-alias").value.split(",").map((it) => it.trim()).filter(Boolean),
    description_candidate: qs("c-review-description").value.trim(),
    granularity_candidate: qs("c-review-granularity").value,
    circuit_kind_candidate: qs("c-review-kind").value,
    loop_type_candidate: qs("c-review-loop-type").value,
    cycle_verified_candidate: !!qs("c-review-cycle-verified").checked,
    confidence_circuit: Number(qs("c-review-confidence").value || 0),
    review_note: qs("c-review-note").value.trim(),
    nodes,
  };
}

async function saveCandidateEdit() {
  const id = qs("review-id").value;
  if (!id) return;
  await api(`/api/candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentCandidatePatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit candidate_id=${id}`);
  await refreshCandidates();
  renderInspector();
}

async function saveCircuitCandidateEdit() {
  const id = qs("c-review-id").value;
  if (!id) return;
  await api(`/api/circuit-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentCircuitPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit circuit_candidate_id=${id}`);
  await refreshCircuitCandidates();
  renderInspector();
}

async function reviewCandidate(action) {
  const id = qs("review-id").value;
  if (!id) return;
  await api(`/api/candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} candidate_id=${id}`);
  await bootstrap();
}

async function reviewCircuitCandidate(action) {
  const id = qs("c-review-id").value;
  if (!id) return;
  await api(`/api/circuit-candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("c-review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} circuit_candidate_id=${id}`);
  await bootstrap();
}

async function runRegionExtraction() {
  const fileId = qs("extract-file-select").value || state.selectedFileId;
  const mode = qs("extract-mode-select").value || "local";
  if (!fileId) {
    alert("璇峰厛閫夋嫨鏂囦欢");
    return;
  }
  const res = await api(`/api/files/${fileId}/extract-regions`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  state.lastExtractSummary = res;
  renderExtractionSummary();
  appendClientLog(`[EXTRACT] run file_id=${fileId} mode=${mode}`);
  await bootstrap();
}

async function runCircuitExtraction() {
  const fileId = qs("circuit-extract-file-select").value || state.selectedFileId;
  const mode = qs("circuit-extract-mode-select").value || "local";
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  const res = await api(`/api/files/${fileId}/extract-circuits`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  state.lastCircuitExtractSummary = res;
  renderCircuitExtractionSummary();
  appendClientLog(`[EXTRACT] circuit_run file_id=${fileId} mode=${mode}`);
  await bootstrap();
}

async function runConnectionExtraction() {
  const fileId = qs("connection-extract-file-select").value || state.selectedFileId;
  const mode = qs("connection-extract-mode-select").value || "local";
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  const res = await api(`/api/files/${fileId}/extract-connections`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  state.lastConnectionExtractSummary = res;
  renderConnectionExtractionSummary();
  appendClientLog(`[EXTRACT] connection_run file_id=${fileId} mode=${mode}`);
  await bootstrap();
}

async function commitApprovedRegions() {
  if (!state.selectedFileId) return;
  const res = await api(`/api/files/${state.selectedFileId}/commit-regions`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCommitResult = res;
  qs("commit-result").textContent = pretty(res);
  appendClientLog(`[UNVERIFIED] stage_from_candidates file_id=${state.selectedFileId}`);
  await refreshUnverified(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function commitApprovedCircuits() {
  if (!state.selectedFileId) return;
  const res = await api(`/api/files/${state.selectedFileId}/commit-circuits`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCircuitCommitResult = res;
  qs("circuit-commit-result").textContent = pretty(res);
  appendClientLog(`[UNVERIFIED] stage_circuit_from_candidates file_id=${state.selectedFileId}`);
  await refreshUnverifiedCircuits(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function validateSelectedUnverified() {
  if (!state.selectedUnverifiedId) {
    alert("请先选择未验证条目");
    return;
  }
  const res = await api(`/api/unverified/${state.selectedUnverifiedId}/validate`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCommitResult = res;
  qs("commit-result").textContent = pretty(res);
  appendClientLog(
    `[VALIDATION] validate_unverified id=${state.selectedUnverifiedId} success=${!!res.success} status=${res.validation_status || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverified(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function promoteSelectedUnverified() {
  if (!state.selectedUnverifiedId) {
    alert("请先选择未验证条目");
    return;
  }
  const res = await api(`/api/unverified/${state.selectedUnverifiedId}/promote`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCommitResult = res;
  qs("commit-result").textContent = pretty(res);
  appendClientLog(
    `[PROMOTE] promote_to_final id=${state.selectedUnverifiedId} success=${!!res.success} table=${res?.promotion?.target_table || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverified(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function validateSelectedUnverifiedCircuit() {
  if (!state.selectedUnverifiedCircuitId) {
    alert("请先选择未验证回路条目");
    return;
  }
  const res = await api(`/api/unverified-circuits/${state.selectedUnverifiedCircuitId}/validate`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCircuitCommitResult = res;
  qs("circuit-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CIRCUIT_VALIDATION] validate_unverified id=${state.selectedUnverifiedCircuitId} success=${!!res.success} status=${res.validation_status || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverifiedCircuits(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function promoteSelectedUnverifiedCircuit() {
  if (!state.selectedUnverifiedCircuitId) {
    alert("请先选择未验证回路条目");
    return;
  }
  const res = await api(`/api/unverified-circuits/${state.selectedUnverifiedCircuitId}/promote`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastCircuitCommitResult = res;
  qs("circuit-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CIRCUIT_PROMOTE] promote_to_final id=${state.selectedUnverifiedCircuitId} success=${!!res.success} table=${res?.promotion?.target_table || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverifiedCircuits(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function batchValidateUnverifiedCircuits() {
  const ids = (state.unverifiedCircuits || []).map((it) => it.id).filter(Boolean);
  if (ids.length === 0) {
    alert("当前无可批量验证回路条目");
    return;
  }
  const res = await api(`/api/unverified-circuits/batch-validate`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user", file_id: state.selectedFileId || "", ids }),
  });
  state.lastCircuitCommitResult = res;
  qs("circuit-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CIRCUIT_BATCH] validate total=${res?.summary?.total || 0} success=${res?.summary?.success_count || 0} failed=${res?.summary?.failed_count || 0}`,
    res?.success ? "info" : "error",
  );
  await refreshUnverifiedCircuits(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function batchPromoteUnverifiedCircuits() {
  const ids = (state.unverifiedCircuits || []).map((it) => it.id).filter(Boolean);
  if (ids.length === 0) {
    alert("当前无可批量提升回路条目");
    return;
  }
  const res = await api(`/api/unverified-circuits/batch-promote`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user", file_id: state.selectedFileId || "", ids }),
  });
  state.lastCircuitCommitResult = res;
  qs("circuit-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CIRCUIT_BATCH] promote total=${res?.summary?.total || 0} success=${res?.summary?.success_count || 0} failed=${res?.summary?.failed_count || 0}`,
    res?.success ? "info" : "error",
  );
  await refreshUnverifiedCircuits(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

function currentConnectionPatch() {
  return {
    en_name_candidate: qs("conn-review-en").value.trim(),
    cn_name_candidate: qs("conn-review-cn").value.trim(),
    alias_candidates: qs("conn-review-alias").value.split(",").map((it) => it.trim()).filter(Boolean),
    description_candidate: qs("conn-review-description").value.trim(),
    granularity_candidate: qs("conn-review-granularity").value,
    connection_modality_candidate: qs("conn-review-modality").value,
    source_region_ref_candidate: qs("conn-review-source").value.trim(),
    target_region_ref_candidate: qs("conn-review-target").value.trim(),
    direction_label: qs("conn-review-direction").value.trim(),
    confidence: Number(qs("conn-review-confidence").value || 0),
    review_note: qs("conn-review-note").value.trim(),
  };
}

async function saveConnectionCandidateEdit() {
  const id = qs("conn-review-id").value;
  if (!id) return;
  await api(`/api/connection-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentConnectionPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit connection_candidate_id=${id}`);
  await refreshConnectionCandidates();
  renderInspector();
}

async function reviewConnectionCandidate(action) {
  const id = qs("conn-review-id").value;
  if (!id) return;
  await api(`/api/connection-candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("conn-review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} connection_candidate_id=${id}`);
  await bootstrap();
}

async function commitApprovedConnections() {
  if (!state.selectedFileId) return;
  const res = await api(`/api/files/${state.selectedFileId}/commit-connections`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastConnectionCommitResult = res;
  qs("connection-commit-result").textContent = pretty(res);
  appendClientLog(`[UNVERIFIED] stage_connection_from_candidates file_id=${state.selectedFileId}`);
  await refreshUnverifiedConnections(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function validateSelectedUnverifiedConnection() {
  if (!state.selectedUnverifiedConnectionId) {
    alert("请先选择未验证连接条目");
    return;
  }
  const res = await api(`/api/unverified-connections/${state.selectedUnverifiedConnectionId}/validate`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastConnectionCommitResult = res;
  qs("connection-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CONNECTION_VALIDATION] validate_unverified id=${state.selectedUnverifiedConnectionId} success=${!!res.success} status=${res.validation_status || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverifiedConnections(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function promoteSelectedUnverifiedConnection() {
  if (!state.selectedUnverifiedConnectionId) {
    alert("请先选择未验证连接条目");
    return;
  }
  const res = await api(`/api/unverified-connections/${state.selectedUnverifiedConnectionId}/promote`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user" }),
  });
  state.lastConnectionCommitResult = res;
  qs("connection-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CONNECTION_PROMOTE] promote_to_final id=${state.selectedUnverifiedConnectionId} success=${!!res.success} table=${res?.promotion?.target_table || "-"}`,
    res.success ? "info" : "error",
  );
  await refreshUnverifiedConnections(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function batchValidateUnverifiedConnections() {
  const ids = (state.unverifiedConnections || []).map((it) => it.id).filter(Boolean);
  if (ids.length === 0) {
    alert("当前无可批量验证连接条目");
    return;
  }
  const res = await api(`/api/unverified-connections/batch-validate`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user", file_id: state.selectedFileId || "", ids }),
  });
  state.lastConnectionCommitResult = res;
  qs("connection-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CONNECTION_BATCH] validate total=${res?.summary?.total || 0} success=${res?.summary?.success_count || 0} failed=${res?.summary?.failed_count || 0}`,
    res?.success ? "info" : "error",
  );
  await refreshUnverifiedConnections(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function batchPromoteUnverifiedConnections() {
  const ids = (state.unverifiedConnections || []).map((it) => it.id).filter(Boolean);
  if (ids.length === 0) {
    alert("当前无可批量提升连接条目");
    return;
  }
  const res = await api(`/api/unverified-connections/batch-promote`, {
    method: "POST",
    body: JSON.stringify({ reviewer: "user", file_id: state.selectedFileId || "", ids }),
  });
  state.lastConnectionCommitResult = res;
  qs("connection-commit-result").textContent = pretty(res);
  appendClientLog(
    `[CONNECTION_BATCH] promote total=${res?.summary?.total || 0} success=${res?.summary?.success_count || 0} failed=${res?.summary?.failed_count || 0}`,
    res?.success ? "info" : "error",
  );
  await refreshUnverifiedConnections(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function restoreSnapshot() {
  try {
    const payload = await api("/api/workbench/snapshot");
    const ss = payload.snapshot || {};
    if (ss.active_tab) setActiveTab(ss.active_tab);
    if (ss.selected_file_id) state.selectedFileId = ss.selected_file_id;
    if (ss.selected_candidate_id) state.selectedCandidateId = ss.selected_candidate_id;
    if (ss.selected_circuit_candidate_id) state.selectedCircuitCandidateId = ss.selected_circuit_candidate_id;
    if (ss.selected_connection_candidate_id) state.selectedConnectionCandidateId = ss.selected_connection_candidate_id;
    if (ss.selected_unverified_id) state.selectedUnverifiedId = ss.selected_unverified_id;
    if (ss.selected_unverified_circuit_id) state.selectedUnverifiedCircuitId = ss.selected_unverified_circuit_id;
    if (ss.selected_unverified_connection_id) state.selectedUnverifiedConnectionId = ss.selected_unverified_connection_id;
  } catch {
    // ignore
  }
}

async function saveSnapshot() {
  const snapshot = {
    active_tab: state.activeTab,
    selected_file_id: state.selectedFileId,
    selected_candidate_id: state.selectedCandidateId,
    selected_circuit_candidate_id: state.selectedCircuitCandidateId,
    selected_connection_candidate_id: state.selectedConnectionCandidateId,
    selected_unverified_id: state.selectedUnverifiedId,
    selected_unverified_circuit_id: state.selectedUnverifiedCircuitId,
    selected_unverified_connection_id: state.selectedUnverifiedConnectionId,
    saved_at: new Date().toISOString(),
  };
  await api("/api/workbench/snapshot", { method: "POST", body: JSON.stringify(snapshot) });
  appendClientLog("[UI] workspace snapshot saved");
}

function bindEvents() {
  document.querySelectorAll(".tab-btn, .nav-item").forEach((el) => {
    el.addEventListener("click", () => setActiveTab(el.dataset.tab));
  });

  qs("btn-refresh").addEventListener("click", async () => {
    await bootstrap();
    appendClientLog("[UI] manual_refresh");
  });

  qs("btn-save-snapshot").addEventListener("click", async () => {
    await saveSnapshot();
  });

  qs("btn-clear-console").addEventListener("click", () => {
    state.logs = [];
    renderConsole();
  });

  qs("file-upload-input").addEventListener("change", async (evt) => {
    try {
      await uploadFile(evt.target);
    } catch (err) {
      appendClientLog(`[ERROR] upload failed reason=${err.message}`, "error");
      alert(`涓婁紶澶辫触: ${err.message}`);
    }
  });

  document.querySelector("#file-table tbody").addEventListener("click", async (evt) => {
    const row = evt.target.closest("tr[data-file-id]");
    const actionBtn = evt.target.closest("button[data-action]");
    if (!row) return;
    const fileId = row.dataset.fileId;
    if (actionBtn) {
      evt.stopPropagation();
      await runFileAction(actionBtn.dataset.action, fileId);
      return;
    }
    await selectFile(fileId);
  });

  qs("btn-reparse-selected").addEventListener("click", async () => {
    if (!state.selectedFileId) return;
    await runFileAction("reparse", state.selectedFileId);
  });

  qs("btn-extract-selected").addEventListener("click", async () => {
    if (!state.selectedFileId) return;
    await runFileAction("extract", state.selectedFileId);
  });

  qs("extract-file-select").addEventListener("change", async (evt) => {
    const fileId = evt.target.value;
    if (fileId) {
      await selectFile(fileId);
    }
  });

  qs("btn-run-region-extract").addEventListener("click", async () => {
    try {
      await runRegionExtraction();
    } catch (err) {
      appendClientLog(`[ERROR] extract failed reason=${err.message}`, "error");
      alert(`鎶藉彇澶辫触: ${err.message}`);
    }
  });

  qs("circuit-extract-file-select").addEventListener("change", async (evt) => {
    const fileId = evt.target.value;
    if (fileId) {
      await selectFile(fileId);
    }
  });

  qs("btn-run-circuit-extract").addEventListener("click", async () => {
    try {
      await runCircuitExtraction();
    } catch (err) {
      appendClientLog(`[ERROR] circuit extract failed reason=${err.message}`, "error");
      alert(`回路抽取失败: ${err.message}`);
    }
  });

  qs("connection-extract-file-select").addEventListener("change", async (evt) => {
    const fileId = evt.target.value;
    if (fileId) {
      await selectFile(fileId);
    }
  });

  qs("btn-run-connection-extract").addEventListener("click", async () => {
    try {
      await runConnectionExtraction();
    } catch (err) {
      appendClientLog(`[ERROR] connection extract failed reason=${err.message}`, "error");
      alert(`连接抽取失败: ${err.message}`);
    }
  });

  document.querySelector("#candidate-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-candidate-id]");
    if (!row) return;
    state.selectedCandidateId = row.dataset.candidateId;
    renderCandidateTable();
    fillCandidateEditor(state.candidates.find((it) => it.id === state.selectedCandidateId));
    renderInspector();
  });

  document.querySelector("#circuit-candidate-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-circuit-candidate-id]");
    if (!row) return;
    state.selectedCircuitCandidateId = row.dataset.circuitCandidateId;
    renderCircuitCandidateTable();
    fillCircuitEditor(state.circuitCandidates.find((it) => it.id === state.selectedCircuitCandidateId));
    renderInspector();
  });

  document.querySelector("#connection-candidate-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-connection-candidate-id]");
    if (!row) return;
    state.selectedConnectionCandidateId = row.dataset.connectionCandidateId;
    renderConnectionCandidateTable();
    fillConnectionEditor(state.connectionCandidates.find((it) => it.id === state.selectedConnectionCandidateId));
    renderInspector();
  });

  qs("btn-review-save").addEventListener("click", async () => {
    try {
      await saveCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] candidate save failed reason=${err.message}`, "error");
      alert(`淇濆瓨澶辫触: ${err.message}`);
    }
  });

  qs("btn-review-approve").addEventListener("click", async () => {
    try {
      await saveCandidateEdit();
      await reviewCandidate("approve");
    } catch (err) {
      appendClientLog(`[ERROR] approve failed reason=${err.message}`, "error");
      alert(`瀹℃牳閫氳繃澶辫触: ${err.message}`);
    }
  });

  qs("btn-review-reject").addEventListener("click", async () => {
    try {
      await saveCandidateEdit();
      await reviewCandidate("reject");
    } catch (err) {
      appendClientLog(`[ERROR] reject failed reason=${err.message}`, "error");
      alert(`瀹℃牳椹冲洖澶辫触: ${err.message}`);
    }
  });

  qs("btn-c-review-save").addEventListener("click", async () => {
    try {
      await saveCircuitCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] circuit candidate save failed reason=${err.message}`, "error");
      alert(`回路候选保存失败: ${err.message}`);
    }
  });

  qs("btn-c-review-approve").addEventListener("click", async () => {
    try {
      await saveCircuitCandidateEdit();
      await reviewCircuitCandidate("approve");
    } catch (err) {
      appendClientLog(`[ERROR] circuit approve failed reason=${err.message}`, "error");
      alert(`回路候选审核通过失败: ${err.message}`);
    }
  });

  qs("btn-c-review-reject").addEventListener("click", async () => {
    try {
      await saveCircuitCandidateEdit();
      await reviewCircuitCandidate("reject");
    } catch (err) {
      appendClientLog(`[ERROR] circuit reject failed reason=${err.message}`, "error");
      alert(`回路候选驳回失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-save").addEventListener("click", async () => {
    try {
      await saveConnectionCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] connection candidate save failed reason=${err.message}`, "error");
      alert(`连接候选保存失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-approve").addEventListener("click", async () => {
    try {
      await saveConnectionCandidateEdit();
      await reviewConnectionCandidate("approve");
    } catch (err) {
      appendClientLog(`[ERROR] connection approve failed reason=${err.message}`, "error");
      alert(`连接候选审核通过失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-reject").addEventListener("click", async () => {
    try {
      await saveConnectionCandidateEdit();
      await reviewConnectionCandidate("reject");
    } catch (err) {
      appendClientLog(`[ERROR] connection reject failed reason=${err.message}`, "error");
      alert(`连接候选驳回失败: ${err.message}`);
    }
  });

  qs("btn-commit-approved").addEventListener("click", async () => {
    try {
      await commitApprovedRegions();
    } catch (err) {
      appendClientLog(`[ERROR] stage to unverified failed reason=${err.message}`, "error");
      alert(`鍏ユ湭楠岃瘉搴撳け璐? ${err.message}`);
    }
  });

  qs("btn-refresh-unverified").addEventListener("click", async () => {
    try {
      await refreshUnverified(state.selectedFileId);
      renderInspector();
    } catch (err) {
      appendClientLog(`[ERROR] refresh unverified failed reason=${err.message}`, "error");
    }
  });

  qs("btn-validate-unverified").addEventListener("click", async () => {
    try {
      await validateSelectedUnverified();
    } catch (err) {
      appendClientLog(`[ERROR] validation failed reason=${err.message}`, "error");
      alert(`鏈獙璇佹潯鐩獙璇佸け璐? ${err.message}`);
    }
  });

  qs("btn-promote-unverified").addEventListener("click", async () => {
    try {
      await promoteSelectedUnverified();
    } catch (err) {
      appendClientLog(`[ERROR] promote failed reason=${err.message}`, "error");
      alert(`鎻愬崌鍒版渶缁堝簱澶辫触: ${err.message}`);
    }
  });

  qs("btn-commit-circuit-approved").addEventListener("click", async () => {
    try {
      await commitApprovedCircuits();
    } catch (err) {
      appendClientLog(`[ERROR] stage circuit to unverified failed reason=${err.message}`, "error");
      alert(`回路入未验证库失败: ${err.message}`);
    }
  });

  qs("btn-refresh-unverified-circuit").addEventListener("click", async () => {
    try {
      await refreshUnverifiedCircuits(state.selectedFileId);
      renderInspector();
    } catch (err) {
      appendClientLog(`[ERROR] refresh unverified circuit failed reason=${err.message}`, "error");
    }
  });

  qs("btn-validate-unverified-circuit").addEventListener("click", async () => {
    try {
      await validateSelectedUnverifiedCircuit();
    } catch (err) {
      appendClientLog(`[ERROR] circuit validation failed reason=${err.message}`, "error");
      alert(`未验证回路验证失败: ${err.message}`);
    }
  });

  qs("btn-batch-validate-unverified-circuit").addEventListener("click", async () => {
    try {
      await batchValidateUnverifiedCircuits();
    } catch (err) {
      appendClientLog(`[ERROR] circuit batch validation failed reason=${err.message}`, "error");
      alert(`批量回路验证失败: ${err.message}`);
    }
  });

  qs("btn-promote-unverified-circuit").addEventListener("click", async () => {
    try {
      await promoteSelectedUnverifiedCircuit();
    } catch (err) {
      appendClientLog(`[ERROR] promote circuit failed reason=${err.message}`, "error");
      alert(`回路提升到最终库失败: ${err.message}`);
    }
  });

  qs("btn-batch-promote-unverified-circuit").addEventListener("click", async () => {
    try {
      await batchPromoteUnverifiedCircuits();
    } catch (err) {
      appendClientLog(`[ERROR] circuit batch promote failed reason=${err.message}`, "error");
      alert(`批量回路提升失败: ${err.message}`);
    }
  });

  qs("btn-commit-connection-approved").addEventListener("click", async () => {
    try {
      await commitApprovedConnections();
    } catch (err) {
      appendClientLog(`[ERROR] stage connection to unverified failed reason=${err.message}`, "error");
      alert(`连接入未验证库失败: ${err.message}`);
    }
  });

  qs("btn-refresh-unverified-connection").addEventListener("click", async () => {
    try {
      await refreshUnverifiedConnections(state.selectedFileId);
      renderInspector();
    } catch (err) {
      appendClientLog(`[ERROR] refresh unverified connection failed reason=${err.message}`, "error");
    }
  });

  qs("btn-validate-unverified-connection").addEventListener("click", async () => {
    try {
      await validateSelectedUnverifiedConnection();
    } catch (err) {
      appendClientLog(`[ERROR] connection validation failed reason=${err.message}`, "error");
      alert(`未验证连接验证失败: ${err.message}`);
    }
  });

  qs("btn-batch-validate-unverified-connection").addEventListener("click", async () => {
    try {
      await batchValidateUnverifiedConnections();
    } catch (err) {
      appendClientLog(`[ERROR] connection batch validation failed reason=${err.message}`, "error");
      alert(`批量连接验证失败: ${err.message}`);
    }
  });

  qs("btn-promote-unverified-connection").addEventListener("click", async () => {
    try {
      await promoteSelectedUnverifiedConnection();
    } catch (err) {
      appendClientLog(`[ERROR] promote connection failed reason=${err.message}`, "error");
      alert(`连接提升到最终库失败: ${err.message}`);
    }
  });

  qs("btn-batch-promote-unverified-connection").addEventListener("click", async () => {
    try {
      await batchPromoteUnverifiedConnections();
    } catch (err) {
      appendClientLog(`[ERROR] connection batch promote failed reason=${err.message}`, "error");
      alert(`批量连接提升失败: ${err.message}`);
    }
  });

  document.querySelector("#unverified-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-unverified-id]");
    if (!row) return;
    state.selectedUnverifiedId = row.dataset.unverifiedId;
    renderUnverifiedTable();
    renderInspector();
  });

  document.querySelector("#unverified-circuit-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-unverified-circuit-id]");
    if (!row) return;
    state.selectedUnverifiedCircuitId = row.dataset.unverifiedCircuitId;
    renderUnverifiedCircuitTable();
    renderInspector();
  });

  document.querySelector("#unverified-connection-table tbody").addEventListener("click", (evt) => {
    const row = evt.target.closest("tr[data-unverified-connection-id]");
    if (!row) return;
    state.selectedUnverifiedConnectionId = row.dataset.unverifiedConnectionId;
    renderUnverifiedConnectionTable();
    renderInspector();
  });

  qs("btn-save-config").addEventListener("click", async () => {
    try {
      await saveConfig();
      await refreshStatus();
      await refreshLogs();
    } catch (err) {
      appendClientLog(`[ERROR] config save failed reason=${err.message}`, "error");
      alert(`閰嶇疆淇濆瓨澶辫触: ${err.message}`);
    }
  });

  document.querySelector("#task-table tbody").addEventListener("click", async (evt) => {
    const row = evt.target.closest("tr[data-task-id]");
    if (!row) return;
    const taskId = row.dataset.taskId;
    const payload = await api(`/api/runs/${taskId}`);
    qs("task-detail").textContent = pretty(payload);
  });
}

async function bootstrap() {
  await refreshStatus();
  await refreshFiles();
  if (state.selectedFileId) {
    await selectFile(state.selectedFileId);
  } else {
    renderFileDetail();
    await refreshCandidates();
    await refreshCircuitCandidates();
    await refreshConnectionCandidates();
    await refreshUnverified();
    await refreshUnverifiedCircuits();
    await refreshUnverifiedConnections();
  }
  await refreshTasks();
  await refreshLogs();
  renderExtractionSummary();
  renderCircuitExtractionSummary();
  renderConnectionExtractionSummary();
  renderUnverifiedTable();
  renderUnverifiedCircuitTable();
  renderUnverifiedConnectionTable();
  renderCircuitCandidateTable();
  renderConnectionCandidateTable();
  renderInspector();
}

window.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await restoreSnapshot();
  await bootstrap();
  setInterval(async () => {
    try {
      await refreshLogs();
    } catch {
      // keep alive
    }
  }, 2500);
});

