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
  regionVersionsList: [],
  /** 脑区提取中心 · 历史版本 */
  regionSelectedVersionId: "",
  /** 脑区审核中心 · 快照表格独立版本（可与提取中心不同） */
  reviewSnapshotVersionId: "",
  regionExtractSubMode: "file",
  /** @type {Set<string>} 脑区审核表格多选 */
  reviewBatchIds: new Set(),
  /** 规则中心最近一次 /api/ontology/rules/bundle */
  rulesCenterBundle: null,
  /** 脑区验证中心 · candidate_region 列表 */
  validationRegionCandidates: [],
  /** 脑区验证中心 · 上部方式切换 local | deepseek | multi */
  validationCenterMode: "local",
  /** 最近一次批量验证结果（供弹窗与应用建议） */
  lastValidationBatch: null,
  /** 批量验证：暂停 / 取消（仅条间生效） */
  validationBatchPaused: false,
  validationBatchCancelled: false,
  validationBatchRunning: false,
};

let regionProgressTimer = null;
let validationProgressTimer = null;

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
  if (tabId === "tab-review-region") {
    (async () => {
      await refreshCandidates();
      await refreshRegionVersions();
    })().catch(() => {});
  } else if (tabId === "tab-review-circuit") {
    refreshCircuitCandidates().catch(() => {});
  } else if (tabId === "tab-review-connection") {
    refreshConnectionCandidates().catch(() => {});
  } else if (tabId === "tab-extract-region") {
    refreshRegionVersions().catch(() => {});
  } else if (tabId === "tab-validation-region") {
    setValidationCenterMode(state.validationCenterMode || "local");
    refreshValidationRegionCandidates().catch(() => {});
  } else if (tabId === "tab-validation-circuit") {
    refreshFinalCircuits().catch(() => {});
  } else if (tabId === "tab-validation-connection") {
    refreshFinalConnections().catch(() => {});
  } else if (tabId === "tab-rules") {
    refreshRulesCenter().catch((err) => {
      appendClientLog(`[ERROR] rules center load failed reason=${err.message}`, "error");
    });
  }
}

function pretty(obj) {
  return JSON.stringify(obj || {}, null, 2);
}

function escapeHtml(s) {
  if (s == null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function refreshRulesCenter() {
  const alertEl = qs("rules-alert");
  if (alertEl) {
    alertEl.hidden = true;
    alertEl.textContent = "";
  }
  const payload = await api("/api/ontology/rules/bundle");
  state.rulesCenterBundle = payload;
  renderRulesCenterBundle(payload);
}

function renderRulesCenterBundle(payload) {
  const rs = payload.ruleset || {};
  const st = payload.status || {};
  const alertEl = qs("rules-alert");
  if (rs._parse_error && alertEl) {
    alertEl.hidden = false;
    alertEl.textContent = `解析规则文件失败: ${rs._parse_error}`;
  }

  const meta = qs("rules-meta");
  if (meta) {
    meta.innerHTML = `
      <div class="rules-meta-card"><span class="rules-meta-k">规则文件</span><span class="rules-meta-v">${escapeHtml(payload.resolved_path || "-")}</span></div>
      <div class="rules-meta-card"><span class="rules-meta-k">加载来源</span><span class="rules-meta-v">${escapeHtml(payload.load_source || "-")}</span></div>
      <div class="rules-meta-card"><span class="rules-meta-k">引擎已加载</span><span class="rules-meta-v">${st.loaded ? "是" : "否"}</span></div>
      <div class="rules-meta-card"><span class="rules-meta-k">规则版本</span><span class="rules-meta-v">${escapeHtml(rs.version || st.rules_version || "-")}</span></div>
      <div class="rules-meta-card"><span class="rules-meta-k">来源说明</span><span class="rules-meta-v">${escapeHtml(rs.source || "-")}</span></div>
      <div class="rules-meta-card"><span class="rules-meta-k">生成时间</span><span class="rules-meta-v">${escapeHtml(rs.generated_at || "-")}</span></div>
    `;
  }

  const termBody = document.querySelector("#rules-table-term tbody");
  if (termBody) {
    termBody.innerHTML = "";
    const tm = rs.termMap || {};
    Object.entries(tm).forEach(([k, v]) => {
      const tr = document.createElement("tr");
      const labels = v && Array.isArray(v.labels) ? v.labels.join("；") : "";
      const can = v && v.canonical ? v.canonical : "";
      tr.innerHTML = `<td>${escapeHtml(k)}</td><td>${escapeHtml(can)}</td><td>${escapeHtml(labels)}</td>`;
      termBody.appendChild(tr);
    });
  }

  const parentBody = document.querySelector("#rules-table-parent tbody");
  if (parentBody) {
    parentBody.innerHTML = "";
    const pr = rs.parentRules || {};
    Object.entries(pr).forEach(([k, v]) => {
      const tr = document.createElement("tr");
      const allowed = v && Array.isArray(v.allowedParents) ? v.allowedParents.join("，") : "";
      tr.innerHTML = `<td>${escapeHtml(k)}</td><td>${escapeHtml(allowed)}</td>`;
      parentBody.appendChild(tr);
    });
  }

  const synBody = document.querySelector("#rules-table-synonym tbody");
  if (synBody) {
    synBody.innerHTML = "";
    const sm = rs.synonymMap || {};
    Object.entries(sm).forEach(([k, v]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td>`;
      synBody.appendChild(tr);
    });
  }

  const cr = qs("rules-classrules");
  if (cr) cr.textContent = pretty(rs.classRules || {});
  const gr = qs("rules-gran-relation");
  if (gr) {
    gr.textContent = pretty({
      granularityRules: rs.granularityRules || {},
      relationRules: rs.relationRules || {},
    });
  }
  const raw = qs("rules-raw-json");
  if (raw) raw.textContent = pretty(rs);

  if (
    alertEl &&
    alertEl.hidden &&
    !rs._parse_error &&
    Object.keys(rs).length === 0 &&
    payload.load_source === "none"
  ) {
    alertEl.hidden = false;
    alertEl.textContent =
      "尚无规则数据：请确认配置中的规则包路径存在 JSON 文件，或在「设置」中导入本体并保存路径。";
  }
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

/** API 返回的 region_duplicates：本批存入的重复 EN/CN 名称提示 */
function notifyRegionDuplicateHint(res) {
  const hintEl = qs("region-duplicate-hint");
  const d = res && res.region_duplicates;
  if (!d || !d.has_duplicates) {
    if (hintEl) {
      hintEl.hidden = true;
      hintEl.textContent = "";
    }
    return;
  }
  const samples = (d.samples || [])
    .slice(0, 5)
    .map((s) => `${s.en || "—"}/${s.cn || "—"}×${s.occurrences}`)
    .join("；");
  const msg = `[提示] 本批存入的脑区存在重复名称：${d.duplicate_group_count} 组，多出 ${d.extra_row_count} 条。示例：${samples || "—"}`;
  if (hintEl) {
    hintEl.hidden = false;
    hintEl.textContent = msg;
  }
  appendClientLog(msg, "warn");
}

function renderConsole() {
  const el = qs("console-content");
  if (!el) return;
  const rows = [...state.logs].slice(-220).map((it) => `[${it.created_at || "-"}] [${it.module || "APP"}] ${it.message || ""}`);
  el.textContent = rows.join("\n");
}

function fileActionButtons(file) {
  return `
    <button class="btn mini" data-action="reparse" data-file-id="${file.file_id}">重新解析</button>
    <button class="btn mini" data-action="extract" data-file-id="${file.file_id}">脑区抽取</button>
    <button class="btn mini" data-action="remove" data-file-id="${file.file_id}">移除</button>
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
  qs("file-preview-content").textContent = previewText || "暂无预览";
  qs("file-normalized-content").textContent = pretty(bundle.normalized || {});

  const metaEl = qs("file-parsed-meta");
  if (metaEl) {
    if (!state.selectedBundle) {
      metaEl.textContent = "（未选择文件）";
    } else {
      const norm = bundle.normalized || {};
      const ccl = norm.content_chunk_layer || {};
      metaEl.textContent = pretty({
        parse_status: doc.parse_status,
        parser_name: doc.parser_name,
        chunk_count: (parsed.chunks || []).length,
        table_rows_in_document: Array.isArray(doc.table_rows) ? doc.table_rows.length : 0,
        content_chunk_layer: {
          row_count: ccl.row_count,
          sheet_names: ccl.sheet_names,
          chunk_count: ccl.chunk_count,
          has_raw_text: ccl.has_raw_text,
          paragraph_count: ccl.paragraph_count,
          table_cell_count: ccl.table_cell_count,
        },
      });
    }
  }
}

function startRegionProgress(label) {
  const wrap = qs("region-progress-wrap");
  const fill = qs("region-progress-fill");
  const lab = qs("region-progress-label");
  if (!wrap || !fill) return;
  wrap.hidden = false;
  if (lab) lab.textContent = label || "执行中…";
  let p = 0;
  fill.style.width = "0%";
  if (regionProgressTimer) clearInterval(regionProgressTimer);
  regionProgressTimer = setInterval(() => {
    p = Math.min(90, p + 2);
    fill.style.width = `${p}%`;
  }, 180);
}

function stopRegionProgress(success, label) {
  if (regionProgressTimer) {
    clearInterval(regionProgressTimer);
    regionProgressTimer = null;
  }
  const wrap = qs("region-progress-wrap");
  const fill = qs("region-progress-fill");
  const lab = qs("region-progress-label");
  if (fill) fill.style.width = success ? "100%" : "0%";
  if (lab) lab.textContent = label || (success ? "完成" : "失败");
  if (wrap) {
    setTimeout(
      () => {
        wrap.hidden = true;
      },
      success ? 500 : 1200,
    );
  }
}

async function withRegionProgress(label, fn) {
  startRegionProgress(label);
  try {
    const res = await fn();
    stopRegionProgress(true, "完成");
    return res;
  } catch (e) {
    stopRegionProgress(false, e.message || "失败");
    throw e;
  }
}

function stopValidationSegmentProgress() {
  if (validationProgressTimer) {
    clearInterval(validationProgressTimer);
    validationProgressTimer = null;
  }
}

function startValidationSegmentProgress(i, total, modeLabel) {
  stopValidationSegmentProgress();
  const fill = qs("validation-progress-fill");
  const lab = qs("validation-progress-label");
  if (!fill || total <= 0) return;
  const segStart = (i / total) * 100;
  const segMax = Math.max(segStart, ((i + 1) / total) * 100 - 0.5);
  let p = segStart;
  fill.style.width = `${p}%`;
  if (lab) lab.textContent = `验证中 ${i + 1} / ${total}（${modeLabel}）…`;
  validationProgressTimer = setInterval(() => {
    if (state.validationBatchPaused) return;
    p = Math.min(segMax, p + 2);
    fill.style.width = `${p}%`;
  }, 180);
}

function setValidationBatchProgressDeterministic(doneCount, total, modeLabel) {
  const fill = qs("validation-progress-fill");
  const lab = qs("validation-progress-label");
  if (fill && total > 0) {
    fill.style.width = `${Math.round((doneCount / total) * 100)}%`;
  }
  if (lab) {
    if (state.validationBatchCancelled) {
      lab.textContent = `已取消 · 已完成 ${doneCount} / ${total}（${modeLabel}）`;
    } else {
      lab.textContent = `验证中 ${doneCount} / ${total}（${modeLabel}）…`;
    }
  }
}

function setValidationExecButtonsDisabled(disabled) {
  ["btn-validation-exec-local", "btn-validation-exec-deepseek", "btn-validation-exec-multi"].forEach((id) => {
    const el = qs(id);
    if (el) el.disabled = !!disabled;
  });
}

function showValidationBatchChrome(showBar, showPauseCancel) {
  const wrap = qs("validation-progress-wrap");
  const pauseBtn = qs("btn-validation-batch-pause");
  const cancelBtn = qs("btn-validation-batch-cancel");
  if (wrap && showBar !== undefined) wrap.hidden = !showBar;
  if (pauseBtn) {
    pauseBtn.hidden = !showPauseCancel;
    pauseBtn.textContent = state.validationBatchPaused ? "继续" : "暂停";
  }
  if (cancelBtn) cancelBtn.hidden = !showPauseCancel;
}

function beginValidationBatchUI(total, modeLabel) {
  state.validationBatchRunning = true;
  state.validationBatchPaused = false;
  state.validationBatchCancelled = false;
  const wrap = qs("validation-progress-wrap");
  const fill = qs("validation-progress-fill");
  const lab = qs("validation-progress-label");
  if (wrap) wrap.hidden = false;
  if (fill) fill.style.width = "0%";
  if (lab) lab.textContent = `验证准备…（共 ${total} 条 · ${modeLabel}）`;
  showValidationBatchChrome(true, true);
  setValidationExecButtonsDisabled(true);
}

function endValidationBatchUI(done, total, modeLabel, cancelled) {
  stopValidationSegmentProgress();
  state.validationBatchRunning = false;
  state.validationBatchPaused = false;
  const fill = qs("validation-progress-fill");
  if (fill && total > 0) {
    if (!cancelled && done >= total) fill.style.width = "100%";
    else fill.style.width = `${Math.round((done / total) * 100)}%`;
  }
  const lab = qs("validation-progress-label");
  if (lab) {
    if (cancelled) lab.textContent = `已取消（${done} / ${total}）· ${modeLabel}`;
    else lab.textContent = `完成（${done} / ${total}）· ${modeLabel}`;
  }
  showValidationBatchChrome(true, false);
  const pauseBtn = qs("btn-validation-batch-pause");
  const cancelBtn = qs("btn-validation-batch-cancel");
  if (pauseBtn) pauseBtn.hidden = true;
  if (cancelBtn) cancelBtn.hidden = true;
  setValidationExecButtonsDisabled(false);
  setTimeout(() => {
    const w = qs("validation-progress-wrap");
    if (w) w.hidden = true;
  }, cancelled ? 900 : 500);
}

async function waitWhileValidationPaused() {
  while (state.validationBatchPaused && !state.validationBatchCancelled) {
    await new Promise((r) => setTimeout(r, 120));
  }
}

const DS_MODAL_STORAGE_KEY = "workbench_region_deepseek_modal_v1";

const DS_FILE_PRESET_OPTIONS = [
  { id: "default", label: "默认（结构化字段）" },
  { id: "detailed", label: "详尽（穷尽候选）" },
  { id: "minimal", label: "精简（单行指令）" },
];

const DS_DIRECT_PRESET_OPTIONS = [
  { id: "default", label: "默认（与内置 build 一致）" },
  { id: "detailed", label: "详尽" },
  { id: "minimal", label: "精简" },
];

let deepseekModalResolver = null;

function dsModalLoadStash() {
  try {
    const raw = localStorage.getItem(DS_MODAL_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function dsModalSaveStash(obj) {
  try {
    localStorage.setItem(DS_MODAL_STORAGE_KEY, JSON.stringify(obj));
  } catch {
    /* ignore */
  }
}

function fillDeepseekModalFromRuntime() {
  const r = state.runtime?.deepseek || {};
  const en = qs("ds-deepseek-enabled");
  const key = qs("ds-deepseek-key");
  const base = qs("ds-deepseek-base");
  const model = qs("ds-deepseek-model");
  const temp = qs("ds-deepseek-temperature");
  if (en) en.checked = !!r.enabled;
  if (key) key.value = r.api_key || "";
  if (base) base.value = r.base_url || "";
  if (model) model.value = r.model || "";
  if (temp) temp.value = r.temperature ?? 0.2;
}

function readDsModalConnectionFields() {
  return {
    enabled: !!(qs("ds-deepseek-enabled") && qs("ds-deepseek-enabled").checked),
    api_key: (qs("ds-deepseek-key")?.value || "").trim(),
    base_url: (qs("ds-deepseek-base")?.value || "").trim(),
    model: (qs("ds-deepseek-model")?.value || "").trim(),
    temperature: Number(qs("ds-deepseek-temperature")?.value ?? 0.2),
  };
}

function updateDsStatusBadge() {
  const badge = qs("ds-status-badge");
  if (!badge) return;
  const enabled = !!(qs("ds-deepseek-enabled")?.checked);
  const key = (qs("ds-deepseek-key")?.value || "").trim();
  if (!enabled) {
    badge.textContent = "未启用";
    badge.className = "ds-status-badge ds-status-warn";
  } else if (!key) {
    badge.textContent = "缺少 API Key";
    badge.className = "ds-status-badge ds-status-error";
  } else {
    badge.textContent = "已配置";
    badge.className = "ds-status-badge ds-status-ok";
  }
}

function populateDeepseekPresetSelects() {
  const fs = qs("ds-file-preset-select");
  const ds = qs("ds-direct-preset-select");
  if (fs) {
    fs.innerHTML = "";
    DS_FILE_PRESET_OPTIONS.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.label;
      fs.appendChild(opt);
    });
  }
  if (ds) {
    ds.innerHTML = "";
    DS_DIRECT_PRESET_OPTIONS.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.label;
      ds.appendChild(opt);
    });
  }
}

async function refreshDeepseekProfileSelect() {
  const sel = qs("ds-profile-select");
  if (!sel) return;
  const data = await api("/api/config/deepseek-profiles");
  const profiles = data.profiles || {};
  sel.innerHTML = "";
  const names = Object.keys(profiles).sort();
  names.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  return data;
}

function applyDeepseekModalStash(kind) {
  const stash = dsModalLoadStash();
  if (qs("ds-file-preset-select") && stash.filePreset) qs("ds-file-preset-select").value = stash.filePreset;
  if (qs("ds-direct-preset-select") && stash.directPreset) qs("ds-direct-preset-select").value = stash.directPreset;
  const fileCustomMode = qs("ds-file-custom-mode");
  if (fileCustomMode) {
    fileCustomMode.checked = !!stash.fileCustomMode;
    const wrap = qs("ds-file-custom-wrap");
    if (wrap) wrap.hidden = !fileCustomMode.checked;
  }
  const directCustomMode = qs("ds-direct-custom-mode");
  if (directCustomMode) {
    directCustomMode.checked = !!stash.directCustomMode;
    const wrap = qs("ds-direct-custom-wrap");
    if (wrap) wrap.hidden = !directCustomMode.checked;
  }
  if (qs("ds-file-custom-template")) qs("ds-file-custom-template").value = stash.fileCustom || "";
  if (qs("ds-direct-custom-template")) qs("ds-direct-custom-template").value = stash.directCustom || "";
  if (qs("ds-system-prompt")) qs("ds-system-prompt").value = stash.system || "";
  if (qs("ds-save-profile-name")) qs("ds-save-profile-name").value = stash.saveName || "";
  if (stash.profileName && qs("ds-profile-select")) {
    const opt = Array.from(qs("ds-profile-select").options).find((o) => o.value === stash.profileName);
    if (opt) qs("ds-profile-select").value = stash.profileName;
  }
}

function stashFromDeepseekModal(kind) {
  dsModalSaveStash({
    filePreset: qs("ds-file-preset-select")?.value || "default",
    directPreset: qs("ds-direct-preset-select")?.value || "default",
    fileCustomMode: !!(qs("ds-file-custom-mode")?.checked),
    directCustomMode: !!(qs("ds-direct-custom-mode")?.checked),
    fileCustom: qs("ds-file-custom-template")?.value || "",
    directCustom: qs("ds-direct-custom-template")?.value || "",
    system: qs("ds-system-prompt")?.value || "",
    saveName: qs("ds-save-profile-name")?.value || "",
    profileName: qs("ds-profile-select")?.value || "",
    lastKind: kind,
  });
}

function buildDeepseekOverrideFromModal(kind) {
  const o = {};
  const sys = (qs("ds-system-prompt")?.value || "").trim();
  if (sys) o.system_prompt = sys;

  if (kind === "direct") {
    const customMode = !!(qs("ds-direct-custom-mode")?.checked);
    if (customMode) {
      const t = (qs("ds-direct-custom-template")?.value || "").trim();
      if (!t) {
        throw new Error("请填写「直接生成」自定义 User 模板，或关闭自定义模板开关");
      }
      o.direct_region_user_prompt_template = t;
    } else {
      o.direct_region_prompt_preset = qs("ds-direct-preset-select")?.value || "default";
    }
  } else {
    const customMode = !!(qs("ds-file-custom-mode")?.checked);
    if (customMode) {
      const t = (qs("ds-file-custom-template")?.value || "").trim();
      if (!t) {
        throw new Error("请填写「文件/文本」自定义 User 模板，或关闭自定义模板开关");
      }
      if (!t.includes("{TEXT}")) {
        throw new Error("文件/文本自定义模板须包含占位符 {TEXT}");
      }
      o.region_user_prompt_template = t;
    } else {
      o.region_prompt_preset = qs("ds-file-preset-select")?.value || "default";
    }
  }
  return o;
}

function openDeepseekRegionModal(kind) {
  return new Promise((resolve) => {
    deepseekModalResolver = resolve;
    const modal = qs("modal-deepseek-region");
    if (!modal) {
      resolve({ profile_key: "", deepseek_override: undefined });
      return;
    }
    (async () => {
      try {
        await refreshStatus();
      } catch (_) {
        /* 使用已有 state.runtime */
      }
      modal.dataset.kind = kind;
      const hint = qs("ds-modal-kind-hint");
      if (hint) {
        hint.textContent =
          kind === "direct" ? "③ 直接生成（DeepSeek）" : kind === "text" ? "② 文本抽取（粘贴文本）" : "① 文件抽取（已解析内容）";
      }
      const secFile = qs("ds-section-file-prompt");
      const secDir = qs("ds-section-direct-prompt");
      if (secFile) secFile.hidden = kind === "direct";
      if (secDir) secDir.hidden = kind !== "direct";

      fillDeepseekModalFromRuntime();
      updateDsStatusBadge();

      try {
        await refreshDeepseekProfileSelect();
      } catch (_) {
        /* 忽略 */
      }
      applyDeepseekModalStash(kind);
      modal.hidden = false;
    })();
  });
}

function closeDeepseekModal(result) {
  const modal = qs("modal-deepseek-region");
  if (modal) modal.hidden = true;
  if (deepseekModalResolver) {
    deepseekModalResolver(result);
    deepseekModalResolver = null;
  }
}

function _versionHintLine(versionId) {
  const n = state.regionVersionsList.length;
  if (!n) return "暂无抽取快照";
  const v =
    state.regionVersionsList.find((x) => x.version_id === versionId) || state.regionVersionsList[0];
  const title = v.title || v.method || "快照";
  return n > 1
    ? `共 ${n} 个快照 · 当前：${title} · ${v.item_count ?? 0} 条`
    : `当前：${title} · ${v.item_count ?? 0} 条`;
}

function updateRegionVersionMeta() {
  const delBtn = qs("btn-region-version-delete");
  const hintEl = qs("region-version-hint");
  const hintReview = qs("review-region-version-hint");
  if (delBtn) {
    delBtn.disabled = !state.regionSelectedVersionId || state.regionVersionsList.length === 0;
  }
  if (hintEl) hintEl.textContent = _versionHintLine(state.regionSelectedVersionId);
  if (hintReview) hintReview.textContent = _versionHintLine(state.reviewSnapshotVersionId);
}

function fillExtractVersionSelect() {
  const sel = qs("region-version-select");
  if (!sel) return;
  sel.innerHTML = "";
  state.regionVersionsList.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v.version_id;
    const title = v.title || v.method || "版本";
    opt.textContent = `${title} · ${v.item_count ?? 0}条`;
    sel.appendChild(opt);
  });
  if (state.regionSelectedVersionId && state.regionVersionsList.some((x) => x.version_id === state.regionSelectedVersionId)) {
    sel.value = state.regionSelectedVersionId;
  }
  sel.disabled = state.regionVersionsList.length === 0;
}

function fillReviewVersionSelect() {
  const sel = qs("review-region-version-select");
  if (!sel) return;
  sel.innerHTML = "";
  state.regionVersionsList.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v.version_id;
    const title = v.title || v.method || "版本";
    opt.textContent = `${title} · ${v.item_count ?? 0}条`;
    sel.appendChild(opt);
  });
  if (state.reviewSnapshotVersionId && state.regionVersionsList.some((x) => x.version_id === state.reviewSnapshotVersionId)) {
    sel.value = state.reviewSnapshotVersionId;
  }
  sel.disabled = state.regionVersionsList.length === 0;
}

function fillRegionVersionSelect() {
  fillExtractVersionSelect();
  fillReviewVersionSelect();
  updateRegionVersionMeta();
}

async function refreshRegionVersions() {
  const fid = state.selectedFileId || (qs("extract-file-select") && qs("extract-file-select").value) || "";
  const hintEl = qs("region-version-hint");
  if (!fid) {
    state.regionVersionsList = [];
    state.regionSelectedVersionId = "";
    state.reviewSnapshotVersionId = "";
    ["region-version-select", "review-region-version-select"].forEach((sid) => {
      const sel = qs(sid);
      if (sel) {
        sel.innerHTML = "";
        sel.disabled = true;
      }
    });
    const delBtn = qs("btn-region-version-delete");
    if (delBtn) delBtn.disabled = true;
    if (hintEl) hintEl.textContent = "";
    const hintReview = qs("review-region-version-hint");
    if (hintReview) hintReview.textContent = "";
    renderRegionExtractTable([]);
    renderReviewSnapshotTable([]);
    return;
  }
  const payload = await api(`/api/region-result-versions?file_id=${encodeURIComponent(fid)}`);
  state.regionVersionsList = payload.versions || [];
  if (!state.regionVersionsList.length) {
    state.regionSelectedVersionId = "";
    state.reviewSnapshotVersionId = "";
    fillRegionVersionSelect();
    renderRegionExtractTable([]);
    renderReviewSnapshotTable([]);
    return;
  }
  const keep = state.regionSelectedVersionId && state.regionVersionsList.some((x) => x.version_id === state.regionSelectedVersionId);
  if (!keep) state.regionSelectedVersionId = state.regionVersionsList[0].version_id;
  const keepR =
    state.reviewSnapshotVersionId && state.regionVersionsList.some((x) => x.version_id === state.reviewSnapshotVersionId);
  if (!keepR) state.reviewSnapshotVersionId = state.regionVersionsList[0].version_id;
  fillRegionVersionSelect();
  await loadExtractRegionVersionTable(state.regionSelectedVersionId);
  await loadReviewSnapshotVersionTable(state.reviewSnapshotVersionId);
  // 版本列表与快照加载会覆盖 reviewSnapshotVersionId；在此之后对齐当前选中候选，避免与右侧编辑器错位
  await syncReviewSnapshotHighlight(state.selectedCandidateId || "");
}

async function deleteSelectedRegionVersion() {
  const vid = state.regionSelectedVersionId;
  if (!vid || !state.regionVersionsList.length) return;
  const meta = state.regionVersionsList.find((x) => x.version_id === vid) || {};
  const label = meta.title || meta.method || vid;
  if (!confirm(`确定删除该抽取结果快照？此操作不可恢复。\n\n${label}`)) return;
  await api(`/api/region-result-versions/${encodeURIComponent(vid)}`, { method: "DELETE" });
  appendClientLog(`[REGION] deleted result snapshot version_id=${vid}`);
  state.regionSelectedVersionId = "";
  state.reviewSnapshotVersionId = "";
  await refreshRegionVersions();
}

async function loadExtractRegionVersionTable(versionId) {
  if (!versionId) {
    renderRegionExtractTable([]);
    return;
  }
  const payload = await api(`/api/region-result-versions/${encodeURIComponent(versionId)}`);
  const ver = payload.version || {};
  renderRegionExtractTable(ver.items || []);
}

async function loadReviewSnapshotVersionTable(versionId) {
  if (!versionId) {
    renderReviewSnapshotTable([]);
    return;
  }
  const payload = await api(`/api/region-result-versions/${encodeURIComponent(versionId)}`);
  const ver = payload.version || {};
  renderReviewSnapshotTable(ver.items || []);
  pickSnapshotRowForReview(state.selectedCandidateId);
  scrollSnapshotPickedIntoView();
}

function pickSnapshotRowForReview(candidateId) {
  document.querySelectorAll("#review-snapshot-table tbody tr.is-snapshot-picked").forEach((tr) => {
    tr.classList.remove("is-snapshot-picked");
  });
  if (!candidateId) return;
  document.querySelectorAll("#review-snapshot-table tbody tr[data-candidate-id]").forEach((tr) => {
    if (tr.dataset.candidateId === candidateId) tr.classList.add("is-snapshot-picked");
  });
}

function snapshotTableHasCandidateRow(candidateId) {
  if (!candidateId) return false;
  let found = false;
  document.querySelectorAll("#review-snapshot-table tbody tr[data-candidate-id]").forEach((tr) => {
    if (tr.dataset.candidateId === candidateId) found = true;
  });
  return found;
}

function scrollSnapshotPickedIntoView() {
  const tr = document.querySelector("#review-snapshot-table tbody tr.is-snapshot-picked");
  if (tr) tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/** 左侧快照与右侧候选对齐：高亮对应行；若当前快照版本不含该候选则切换到包含它的版本 */
async function syncReviewSnapshotHighlight(candidateId) {
  if (!candidateId) {
    pickSnapshotRowForReview("");
    return;
  }
  pickSnapshotRowForReview(candidateId);
  if (snapshotTableHasCandidateRow(candidateId)) {
    scrollSnapshotPickedIntoView();
    return;
  }
  if (!state.selectedFileId) return;
  try {
    const res = await api(
      `/api/region-result-versions/by-candidate?candidate_id=${encodeURIComponent(candidateId)}&file_id=${encodeURIComponent(state.selectedFileId)}`,
    );
    const vid = (res.version_id || "").trim();
    if (!vid) return;
    if (!state.regionVersionsList.some((x) => x.version_id === vid)) {
      await refreshRegionVersions();
    }
    state.reviewSnapshotVersionId = vid;
    const sel = qs("review-region-version-select");
    if (sel && state.regionVersionsList.some((x) => x.version_id === vid)) {
      sel.value = vid;
    }
    updateRegionVersionMeta();
    const payload = await api(`/api/region-result-versions/${encodeURIComponent(vid)}`);
    const ver = payload.version || {};
    renderReviewSnapshotTable(ver.items || []);
    pickSnapshotRowForReview(candidateId);
    scrollSnapshotPickedIntoView();
  } catch {
    pickSnapshotRowForReview(candidateId);
  }
}

function renderRegionExtractTable(items) {
  const tbody = document.querySelector("#region-extract-result-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  (items || []).forEach((it) => {
    const extractStatus = parseExtractStatus(it);
    const tr = document.createElement("tr");
    tr.dataset.extractStatus = extractStatus;
    // 构建各列 HTML
    const tdId = `<td style="font-size:10px;color:#64748b;max-width:9rem;overflow:hidden;text-overflow:ellipsis;">${it.id || "-"}</td>`;
    const tdEn = `<td style="font-weight:500;">${it.en_name_candidate || ""}</td>`;
    const tdCn = `<td>${it.cn_name_candidate || ""}</td>`;
    const tdGran = `<td style="font-size:11px;">${it.granularity_candidate || ""}</td>`;
    const tdLane = `<td style="font-size:11px;">${it.lane || ""}</td>`;
    const tdStatus = `<td>${xbadgeHtml(extractStatus)}</td>`;
    const tdMethod = `<td>${methodBadgeHtml(it.extraction_method)}</td>`;
    const tdConf = `<td style="font-size:11px;">${it.confidence != null ? Number(it.confidence).toFixed(2) : ""}</td>`;
    const srcFull = String(it.source_text || "");
    const srcShort = srcFull.length > 80 ? srcFull.slice(0, 80) + "…" : srcFull;
    const tdSrc = `<td style="font-size:11px;color:var(--muted);" title="${srcFull.replace(/"/g, "&quot;")}">${srcShort}</td>`;
    tr.innerHTML = tdId + tdEn + tdCn + tdGran + tdLane + tdStatus + tdMethod + tdConf + tdSrc;
    tbody.appendChild(tr);
  });
}

function renderReviewSnapshotTable(items) {
  const tbody = document.querySelector("#review-snapshot-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  (items || []).forEach((it) => {
    const extractStatus = parseExtractStatus(it);
    const tr = document.createElement("tr");
    tr.dataset.extractStatus = extractStatus;
    if (it.id) tr.dataset.candidateId = it.id;
    const tdId = `<td style="font-size:10px;color:#64748b;max-width:6rem;overflow:hidden;text-overflow:ellipsis;">${it.id || "-"}</td>`;
    const tdEn = `<td style="font-weight:500;">${it.en_name_candidate || ""}</td>`;
    const tdCn = `<td>${it.cn_name_candidate || ""}</td>`;
    const tdGran = `<td style="font-size:11px;">${it.granularity_candidate || ""}</td>`;
    const tdLane = `<td style="font-size:11px;">${it.lane || ""}</td>`;
    const tdStatus = `<td>${xbadgeHtml(extractStatus)}</td>`;
    const tdMethod = `<td>${methodBadgeHtml(it.extraction_method)}</td>`;
    const tdConf = `<td style="font-size:11px;">${it.confidence != null ? Number(it.confidence).toFixed(2) : ""}</td>`;
    const srcFull = String(it.source_text || "");
    const srcShort = srcFull.length > 64 ? srcFull.slice(0, 64) + "…" : srcFull;
    const tdSrc = `<td style="font-size:11px;color:var(--muted);" title="${srcFull.replace(/"/g, "&quot;")}">${srcShort}</td>`;
    tr.innerHTML = tdId + tdEn + tdCn + tdGran + tdLane + tdStatus + tdMethod + tdConf + tdSrc;
    tbody.appendChild(tr);
  });
}

function setRegionExtractMode(mode) {
  state.regionExtractSubMode = mode;
  document.querySelectorAll(".region-mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.regionMode === mode);
  });
  const pf = qs("region-panel-file");
  const pt = qs("region-panel-text");
  const pd = qs("region-panel-direct");
  if (pf) pf.hidden = mode !== "file";
  if (pt) pt.hidden = mode !== "text";
  if (pd) pd.hidden = mode !== "direct";
}

function renderCircuitExtractionSummary() {
  qs("circuit-extract-summary").textContent = pretty(state.lastCircuitExtractSummary || {});
}

function renderConnectionExtractionSummary() {
  qs("connection-extract-summary").textContent = pretty(state.lastConnectionExtractSummary || {});
}

/** 从 review_note JSON 解析统一 extract_status */
function parseExtractStatus(candidate) {
  let note = {};
  try { note = JSON.parse(candidate.review_note || "{}"); } catch { /* */ }
  // 优先取顶层 extract_status（DeepSeek / local_rule 都会写）
  if (note.extract_status) return note.extract_status;
  // v2 pipeline 写在 wb_v2.extract_status
  if (note.wb_v2?.extract_status) return note.wb_v2.extract_status;
  // local_rule 嵌套
  if (note.local_rule?.extract_status) return note.local_rule.extract_status;
  return "pending_review";
}

/** 从 review_note JSON 解析 ontology_check（本体规则命中） */
function parseOntologyCheck(candidate) {
  if (!candidate || !candidate.review_note) return null;
  try {
    const n = JSON.parse(candidate.review_note);
    if (n && n.ontology_check) return n.ontology_check;
  } catch {}
  return null;
}

/** 抽取阶段写入的 ontology_binding.term_key（便于验收） */
function parseOntologyBindingTermKey(candidate) {
  if (!candidate || !candidate.review_note) return "";
  try {
    const n = JSON.parse(candidate.review_note);
    const tk = n?.ontology_binding?.term_key;
    return typeof tk === "string" ? tk : "";
  } catch {
    return "";
  }
}

function ontologyBadgeHtml(oc) {
  if (!oc || !oc.issues || !oc.issues.length) {
    return '<span class="ontology-badge ok" title="无本体规则问题">—</span>';
  }
  const hard = oc.issues.filter((i) => i.severity === "hard").length;
  const warn = oc.issues.filter((i) => i.severity === "warn").length;
  const parts = [];
  if (hard) parts.push(`<span class="ontology-badge hard" title="hard">${hard}H</span>`);
  if (warn) parts.push(`<span class="ontology-badge warn" title="warn">${warn}W</span>`);
  return parts.join(" ");
}

const EXTRACT_STATUS_LABEL = {
  confirmed:     "✓ 确认",
  review_needed: "? 待审",
  unresolved:    "✗ 待解",
  rejected:      "✗ 排除",
  pending_review:"· 待审核",
};

const METHOD_LABEL = {
  deepseek:        "DeepSeek",
  kimi:            "Kimi",
  multi:           "双模型",
  local_rule:      "本地规则",
  region_v2_local: "V2本地",
  region_v2_deepseek: "V2+DS",
  direct_deepseek: "直接生成(DS)",
  direct_kimi:     "直接生成(Kimi)",
};

function xbadgeHtml(status) {
  const cls = `xbadge xbadge-${CSS.escape ? status : status}`;
  const label = EXTRACT_STATUS_LABEL[status] || status;
  return `<span class="xbadge xbadge-${status}">${label}</span>`;
}

function methodBadgeHtml(method) {
  const m = (method || "").toLowerCase();
  let cls = "method-unknown";
  if (m.startsWith("deepseek")) cls = "method-deepseek";
  else if (m === "kimi" || m.startsWith("direct_kimi")) cls = "method-kimi";
  else if (m === "multi") cls = "method-multi";
  else if (m === "local_rule") cls = "method-local_rule";
  else if (m.startsWith("region_v2")) cls = "method-region_v2";
  const label = METHOD_LABEL[method] || method || "未知";
  return `<span class="method-badge ${cls}">${label}</span>`;
}

function evidenceChipHtml(sourceText) {
  if (!sourceText) return '<span style="color:var(--muted);font-size:11px;">—</span>';
  const escaped = sourceText.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const short = sourceText.length > 40 ? sourceText.slice(0, 40) + "…" : sourceText;
  return `<span class="evidence-chip" title="${escaped}">${short.replace(/</g, "&lt;")}</span>`;
}

/** 当前过滤条件 */
const _reviewFilter = { status: "", method: "" };

/** 从下拉同步过滤并刷新候选表（改选即时生效） */
function applyReviewFiltersFromDom() {
  _reviewFilter.status = (qs("review-filter-status")?.value || "");
  _reviewFilter.method = (qs("review-filter-method")?.value || "");
  state.reviewBatchIds.clear();
  renderCandidateTable();
}

function getFilteredCandidateRows() {
  return (state.candidates || []).filter((it) => {
    if (_reviewFilter.status) {
      if (parseExtractStatus(it) !== _reviewFilter.status) return false;
    }
    if (_reviewFilter.method) {
      const m = (it.extraction_method || "").toLowerCase();
      const f = _reviewFilter.method.toLowerCase();
      // deepseek：匹配方法名中含 deepseek 的轨（如 deepseek、region_v2_deepseek），避免仅 startsWith 漏掉
      if (f === "deepseek") {
        if (!m.includes("deepseek")) return false;
      } else if (!m.startsWith(f)) {
        return false;
      }
    }
    return true;
  });
}

/** 当前过滤列表中，用于保存/审核后跳转的下一条 id（末行则回到上一行） */
function getNextRegionCandidateIdAfterCurrent(currentId) {
  const rows = getFilteredCandidateRows();
  const idx = rows.findIndex((r) => r.id === currentId);
  if (rows.length === 0) return "";
  if (idx === -1) return rows[0].id;
  if (idx + 1 < rows.length) return rows[idx + 1].id;
  if (idx > 0) return rows[idx - 1].id;
  return rows[0].id;
}

function getNextCircuitCandidateIdAfterCurrent(currentId) {
  const rows = state.circuitCandidates || [];
  const idx = rows.findIndex((r) => r.id === currentId);
  if (rows.length === 0) return "";
  if (idx === -1) return rows[0].id;
  if (idx + 1 < rows.length) return rows[idx + 1].id;
  if (idx > 0) return rows[idx - 1].id;
  return rows[0].id;
}

function getNextConnectionCandidateIdAfterCurrent(currentId) {
  const rows = state.connectionCandidates || [];
  const idx = rows.findIndex((r) => r.id === currentId);
  if (rows.length === 0) return "";
  if (idx === -1) return rows[0].id;
  if (idx + 1 < rows.length) return rows[idx + 1].id;
  if (idx > 0) return rows[idx - 1].id;
  return rows[0].id;
}

async function refreshRegionReviewAfterSaveAndSelect(nextId) {
  state.selectedCandidateId = nextId || "";
  await refreshCandidates();
  await refreshUnverified(state.selectedFileId);
  await refreshTasks();
  await refreshLogs();
  renderInspector();
}

async function refreshCircuitReviewAfterSaveAndSelect(nextId) {
  state.selectedCircuitCandidateId = nextId || "";
  await refreshCircuitCandidates();
  await refreshUnverifiedCircuits(state.selectedFileId);
  await refreshTasks();
  await refreshLogs();
  renderInspector();
}

async function refreshConnectionReviewAfterSaveAndSelect(nextId) {
  state.selectedConnectionCandidateId = nextId || "";
  await refreshConnectionCandidates();
  await refreshUnverifiedConnections(state.selectedFileId);
  await refreshTasks();
  await refreshLogs();
  renderInspector();
}

function syncReviewSelectAllCheckbox() {
  const el = qs("review-select-all");
  if (!el) return;
  const rows = getFilteredCandidateRows();
  if (!rows.length) {
    el.checked = false;
    el.indeterminate = false;
    return;
  }
  const all = rows.every((r) => state.reviewBatchIds.has(r.id));
  const some = rows.some((r) => state.reviewBatchIds.has(r.id));
  el.checked = all;
  el.indeterminate = !all && some;
}

function renderCandidateTable() {
  const tbody = document.querySelector("#candidate-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const uvByCandidate = new Map((state.unverifiedRegions || []).map((row) => [row.source_candidate_region_id, row]));
  const candidates = getFilteredCandidateRows();
  candidates.forEach((it) => {
    const uv = uvByCandidate.get(it.id);
    const extractStatus = parseExtractStatus(it);
    const tr = document.createElement("tr");
    tr.className = it.id === state.selectedCandidateId ? "is-selected" : "";
    tr.dataset.candidateId = it.id;
    tr.dataset.extractStatus = extractStatus;
    const cbChecked = state.reviewBatchIds.has(it.id) ? " checked" : "";
    tr.innerHTML = `
      <td class="review-td-cb"><input type="checkbox" class="review-cb" data-candidate-id="${it.id || ""}"${cbChecked} /></td>
      <td style="font-size:10px;color:#64748b;max-width:7rem;overflow:hidden;text-overflow:ellipsis;">${it.id || "-"}</td>
      <td style="font-weight:500;">${it.en_name_candidate || "-"}</td>
      <td>${it.cn_name_candidate || "-"}</td>
      <td style="font-size:11px;">${it.granularity_candidate || "-"}</td>
      <td>${xbadgeHtml(extractStatus)}</td>
      <td>${methodBadgeHtml(it.extraction_method)}</td>
      <td>${evidenceChipHtml(it.source_text)}</td>
      <td style="font-size:11px;">${it.confidence != null ? Number(it.confidence).toFixed(2) : "-"}</td>
      <td style="font-size:11px;">${it.status || "-"}</td>
      <td style="font-size:11px;">${uv ? uv.id : "-"}</td>
      <td style="font-size:11px;">${uv ? (uv.validation_status || "-") : "-"}</td>
      <td style="font-size:11px;">${ontologyBadgeHtml(parseOntologyCheck(it))}</td>
      <td style="font-size:10px;color:#64748b;max-width:8rem;overflow:hidden;text-overflow:ellipsis;" title="${(parseOntologyBindingTermKey(it) || "—").replace(/"/g, "&quot;")}">${parseOntologyBindingTermKey(it) || "—"}</td>
    `;
    tbody.appendChild(tr);
  });
  syncReviewSelectAllCheckbox();
  void syncReviewSnapshotHighlight(state.selectedCandidateId);
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
      <td>${ontologyBadgeHtml(parseOntologyCheck(it))}</td>
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
      <td>${ontologyBadgeHtml(parseOntologyCheck(it))}</td>
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
  const statusBadgeEl = qs("review-extract-status-badge");
  const methodBadgeEl = qs("review-method-badge");
  const sourceTextEl  = qs("review-source-text");
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
    const roc = qs("review-ontology-check");
    if (roc) roc.textContent = "";
    if (statusBadgeEl) statusBadgeEl.innerHTML = "";
    if (methodBadgeEl) methodBadgeEl.innerHTML = "";
    if (sourceTextEl) sourceTextEl.value = "";
    void syncReviewSnapshotHighlight("");
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
  // 状态 badge
  const extractStatus = parseExtractStatus(candidate);
  if (statusBadgeEl) statusBadgeEl.innerHTML = xbadgeHtml(extractStatus);
  if (methodBadgeEl) methodBadgeEl.innerHTML = methodBadgeHtml(candidate.extraction_method);
  if (sourceTextEl) sourceTextEl.value = candidate.source_text || "";
  const roc = qs("review-ontology-check");
  if (roc) {
    const oc = parseOntologyCheck(candidate);
    roc.textContent = oc ? JSON.stringify(oc, null, 2) : "(无本体规则命中)";
  }
  void syncReviewSnapshotHighlight(candidate.id);
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
    const coc = qs("c-review-ontology-check");
    if (coc) coc.textContent = "";
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
  const coc = qs("c-review-ontology-check");
  if (coc) {
    const oc = parseOntologyCheck(candidate);
    coc.textContent = oc ? JSON.stringify(oc, null, 2) : "(无本体规则命中)";
  }
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
    const uoc = qs("conn-review-ontology-check");
    if (uoc) uoc.textContent = "";
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
  const uoc = qs("conn-review-ontology-check");
  if (uoc) {
    const oc = parseOntologyCheck(candidate);
    uoc.textContent = oc ? JSON.stringify(oc, null, 2) : "(无本体规则命中)";
  }
}

function syncOntologyStatusHint(or) {
  const el = qs("cfg-ontology-status-hint");
  if (!el) return;
  if (!or) {
    el.textContent = "";
    return;
  }
  if (or.loaded) {
    el.textContent = `已加载 rules_version=${or.rules_version || ""}`;
  } else {
    el.textContent = or.load_error || "未加载";
  }
}

function syncConfigPanel(runtime) {
  state.runtime = runtime;
  qs("cfg-deepseek-enabled").checked = !!runtime?.deepseek?.enabled;
  qs("cfg-deepseek-key").value = runtime?.deepseek?.api_key || "";
  qs("cfg-deepseek-base").value = runtime?.deepseek?.base_url || "";
  qs("cfg-deepseek-model").value = runtime?.deepseek?.model || "";
  qs("cfg-deepseek-temperature").value = runtime?.deepseek?.temperature ?? 0.2;
  if (qs("cfg-moonshot-enabled")) qs("cfg-moonshot-enabled").checked = !!runtime?.moonshot?.enabled;
  if (qs("cfg-moonshot-key")) qs("cfg-moonshot-key").value = runtime?.moonshot?.api_key || "";
  if (qs("cfg-moonshot-base")) qs("cfg-moonshot-base").value = runtime?.moonshot?.base_url || "";
  if (qs("cfg-moonshot-model")) qs("cfg-moonshot-model").value = runtime?.moonshot?.model || "";
  if (qs("cfg-moonshot-temperature")) qs("cfg-moonshot-temperature").value = runtime?.moonshot?.temperature ?? 0.2;
  qs("cfg-normalize-mode").value = runtime?.pipeline?.normalize_mode_default || "local";
  qs("cfg-validate-mode").value = runtime?.pipeline?.validate_mode_default || "local";
  const or = runtime?.pipeline?.ontology_rules || {};
  if (qs("cfg-ontology-enabled")) qs("cfg-ontology-enabled").checked = !!or.enabled;
  if (qs("cfg-ontology-path")) qs("cfg-ontology-path").value = or.path || "";
  if (qs("cfg-ontology-stage-policy")) qs("cfg-ontology-stage-policy").value = or.stage_policy || "warn";
  if (qs("cfg-auto-validate-on-extract")) qs("cfg-auto-validate-on-extract").checked = !!runtime?.pipeline?.auto_validate_on_extract;
}

function syncExtractSelectors() {
  const select = qs("extract-file-select");
  const circuitSelect = qs("circuit-extract-file-select");
  const connectionSelect = qs("connection-extract-file-select");
  const finalCircuitSel = qs("final-circuit-file-select");
  const finalConnSel = qs("final-connection-file-select");
  select.innerHTML = "";
  circuitSelect.innerHTML = "";
  connectionSelect.innerHTML = "";
  if (finalCircuitSel) finalCircuitSel.innerHTML = "";
  if (finalConnSel) finalConnSel.innerHTML = "";
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

    if (finalCircuitSel) {
      const o = document.createElement("option");
      o.value = f.file_id;
      o.textContent = `${f.filename} (${f.file_type})`;
      finalCircuitSel.appendChild(o);
    }
    if (finalConnSel) {
      const o = document.createElement("option");
      o.value = f.file_id;
      o.textContent = `${f.filename} (${f.file_type})`;
      finalConnSel.appendChild(o);
    }
  });
  if (state.selectedFileId) {
    select.value = state.selectedFileId;
    circuitSelect.value = state.selectedFileId;
    connectionSelect.value = state.selectedFileId;
    if (finalCircuitSel) finalCircuitSel.value = state.selectedFileId;
    if (finalConnSel) finalConnSel.value = state.selectedFileId;
  }
}

function pickRowField(row, keys) {
  for (const k of keys) {
    const v = row[k];
    if (v != null && v !== "") return v;
  }
  return "";
}

function collectValidationRowPatch(tr) {
  const patch = {};
  tr.querySelectorAll(".vr-field[data-field]").forEach((el) => {
    const f = el.dataset.field;
    if (f === "alias_candidates") {
      try {
        patch.alias_candidates = JSON.parse(el.value || "[]");
      } catch {
        throw new Error("alias_candidates 需为合法 JSON 数组");
      }
    } else if (f === "confidence") {
      patch.confidence = Number(el.value || 0);
    } else {
      patch[f] = el.value;
    }
  });
  return patch;
}

function setValidationCenterMode(mode) {
  if (mode) state.validationCenterMode = mode;
  const m = state.validationCenterMode || "local";
  document.querySelectorAll(".validation-mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.validationMode === m);
  });
  const panels = {
    local: "validation-panel-local",
    deepseek: "validation-panel-deepseek",
    multi: "validation-panel-multi",
  };
  Object.entries(panels).forEach(([key, id]) => {
    const p = qs(id);
    if (p) p.hidden = key !== m;
  });
}

function renderValidationRegionTable() {
  const tbody = document.querySelector("#validation-region-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  state.validationRegionCandidates.forEach((row) => {
    const tr = document.createElement("tr");
    const cid = row.id || "";
    tr.dataset.candidateId = cid;
    const aliases = Array.isArray(row.alias_candidates)
      ? JSON.stringify(row.alias_candidates)
      : JSON.stringify(row.alias_candidates || []);
    tr.innerHTML = `
      <td class="mono td-shrink">${escapeHtml(cid)}</td>
      <td class="mono td-shrink">${escapeHtml(row.global_region_id || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.file_id || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.lane || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.parsed_document_id || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.chunk_id || "")}</td>
      <td><textarea class="vr-field" data-field="source_text" rows="2"></textarea></td>
      <td><input class="vr-field" data-field="en_name_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="cn_name_candidate" type="text" /></td>
      <td><textarea class="vr-field" data-field="alias_candidates" rows="2"></textarea></td>
      <td><input class="vr-field" data-field="laterality_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="granularity_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="region_category_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="parent_region_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="ontology_source_candidate" type="text" /></td>
      <td><input class="vr-field" data-field="confidence" type="number" step="0.0001" min="0" max="1" /></td>
      <td class="mono td-shrink">${escapeHtml(row.extraction_method || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.llm_model || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.status || "")}</td>
      <td><textarea class="vr-field vr-field--note" data-field="review_note" rows="2"></textarea></td>
      <td class="mono td-shrink">${escapeHtml(row.created_at || "")}</td>
      <td class="mono td-shrink">${escapeHtml(row.updated_at || "")}</td>
      <td class="vr-actions"><button type="button" class="btn mini" data-vr-action="save">保存</button></td>
    `;
    const set = (selector, val) => {
      const el = tr.querySelector(selector);
      if (el) el.value = val != null ? String(val) : "";
    };
    set("textarea[data-field=source_text]", row.source_text);
    set("input[data-field=en_name_candidate]", row.en_name_candidate);
    set("input[data-field=cn_name_candidate]", row.cn_name_candidate);
    set("textarea[data-field=alias_candidates]", aliases);
    set("input[data-field=laterality_candidate]", row.laterality_candidate);
    set("input[data-field=granularity_candidate]", row.granularity_candidate);
    set("input[data-field=region_category_candidate]", row.region_category_candidate);
    set("input[data-field=parent_region_candidate]", row.parent_region_candidate);
    set("input[data-field=ontology_source_candidate]", row.ontology_source_candidate);
    set("input[data-field=confidence]", row.confidence);
    set("textarea[data-field=review_note]", row.review_note || "");
    tbody.appendChild(tr);
  });
}

function summarizePipelineRow(data) {
  if (!data || !data.steps) return null;
  const s = data.steps;
  const llm = data.llm || {};
  return {
    local_verdict: s.local && s.local.verdict,
    completeness_ok: s.completeness && s.completeness.ok,
    missing_fields: s.completeness && s.completeness.missing_fields,
    needs_llm: s.needs_llm,
    invoke_llm: s.invoke_llm,
    llm_skipped: s.llm_skipped,
    kimi_ok: llm.kimi_ok,
    deepseek_ok: llm.deepseek_ok,
    partial: llm.partial,
    partial_note: llm.partial_note,
  };
}

function validationCenterModeToLlmMode(uiMode) {
  if (uiMode === "local") return "none";
  if (uiMode === "deepseek") return "deepseek";
  return "multi";
}

function showValidationResultModal() {
  const batch = state.lastValidationBatch;
  const backdrop = qs("modal-validation-result");
  const summary = qs("modal-validation-result-summary");
  const detail = qs("modal-validation-result-detail");
  const hint = qs("modal-validation-result-suggest-hint");
  const btnApply = qs("btn-modal-validation-apply");
  if (!backdrop || !summary || !detail) return;
  if (!batch || !batch.rows) {
    backdrop.hidden = true;
    return;
  }
  const { mode, rows, cancelled } = batch;
  const ok = rows.filter((r) => r.ok).length;
  const fail = rows.length - ok;
  const withPatch = rows.filter(
    (r) => r.ok && r.proposed_patch && Object.keys(r.proposed_patch).length > 0,
  ).length;
  const cancelNote = cancelled ? " · 已取消" : "";
  summary.textContent = `模式：${mode}${cancelNote} · 成功 ${ok} 条 · 失败 ${fail} 条 · 含可同步修改 ${withPatch} 条（先校验→完整性→按需 LLM）`;
  const compact = rows.map((r) =>
    r.ok
      ? {
          candidate_id: r.candidateId,
          ok: true,
          proposed_patch: r.proposed_patch || null,
          summary: summarizePipelineRow(r.data),
        }
      : { candidate_id: r.candidateId, ok: false, error: r.error },
  );
  let str = JSON.stringify(compact, null, 2);
  if (str.length > 14000) str = `${str.slice(0, 14000)}\n…（内容过长已截断）`;
  detail.textContent = str;
  if (hint && btnApply) {
    if (withPatch > 0) {
      hint.hidden = false;
      hint.textContent = `有 ${withPatch} 条含模型生成的字段修改建议，确认后「应用」将一次性写入数据库（含 review_note 流水线摘要）。`;
      btnApply.hidden = false;
    } else {
      hint.hidden = true;
      btnApply.hidden = true;
    }
  }
  backdrop.hidden = false;
}

function closeValidationResultModal() {
  const backdrop = qs("modal-validation-result");
  if (backdrop) backdrop.hidden = true;
}

async function applyPendingValidationSuggestions() {
  const batch = state.lastValidationBatch;
  if (!batch || !batch.rows) return;
  let n = 0;
  for (const r of batch.rows) {
    if (!r.ok || !r.proposed_patch || !Object.keys(r.proposed_patch).length) continue;
    try {
      const resp = await fetch(`/api/candidates/${encodeURIComponent(r.candidateId)}/validation-pipeline/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          patch: r.proposed_patch,
          pipeline_meta: { steps: r.data.steps, llm: r.data.llm },
          reviewer: "user",
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.ok === false) throw new Error(data.error || "apply_failed");
      n++;
    } catch (e) {
      appendClientLog(`[ERROR] apply pipeline id=${r.candidateId} reason=${e.message}`, "error");
    }
  }
  appendClientLog(`[UI] applied validation pipeline patches count=${n}`);
  closeValidationResultModal();
  await refreshValidationRegionCandidates();
}

async function refreshValidationRegionCandidates() {
  const meta = qs("validation-region-meta");
  const tbody = document.querySelector("#validation-region-table tbody");
  if (!tbody) return;
  const lane = (qs("validation-region-lane-select") && qs("validation-region-lane-select").value) || "local";
  tbody.innerHTML = "";
  try {
    const data = await api(`/api/region-candidates?lane=${encodeURIComponent(lane)}`);
    state.validationRegionCandidates = data.items || [];
    if (meta) meta.textContent = `共 ${state.validationRegionCandidates.length} 条（数据库 candidate_region · lane=${lane}）`;
    renderValidationRegionTable();
  } catch (err) {
    if (meta) meta.textContent = `加载失败: ${err.message}`;
  }
}

async function saveValidationRegionRow(candidateId, tr) {
  const patch = collectValidationRowPatch(tr);
  let res = await saveRegionCandidatePatch(candidateId, patch);
  if (res.duplicate_conflict) {
    const choice = await openRegionDuplicateSaveModal(res.duplicate_conflict);
    if (choice === "replace") {
      res = await saveRegionCandidatePatch(candidateId, patch, "replace_others");
    } else if (choice === "keep") {
      res = await saveRegionCandidatePatch(candidateId, patch, "keep_duplicates");
    } else {
      return;
    }
    if (!res.ok) throw new Error(res.error || "save_failed");
  }
  appendClientLog(`[UI] validation center saved candidate_id=${candidateId}`);
  await refreshValidationRegionCandidates();
}

async function runValidationPipelineRow(candidateId, opts = {}) {
  const skipRefresh = !!opts.skipRefresh;
  const llmMode = validationCenterModeToLlmMode(state.validationCenterMode || "local");
  const resp = await fetch(`/api/candidates/${encodeURIComponent(candidateId)}/validation-pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ llm_mode: llmMode, reviewer: "user" }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || data.detail || `HTTP_${resp.status}`);
  }
  if (!skipRefresh) {
    appendClientLog(`[UI] validation pipeline candidate_id=${candidateId}`);
    await refreshValidationRegionCandidates();
  }
  return data;
}

async function runValidationBatch() {
  const mode = state.validationCenterMode || "local";
  const ids = state.validationRegionCandidates.map((r) => r.id).filter(Boolean);
  const meta = qs("validation-region-meta");
  if (!ids.length) {
    alert("请先点击「从数据库刷新」加载候选。");
    return;
  }
  const label = mode === "local" ? "本地（无 LLM）" : mode === "deepseek" ? "DeepSeek" : "Kimi+DeepSeek";
  if (!window.confirm(`将对当前列表共 ${ids.length} 条执行验证流水线（正确性→完整性→按需 ${label}），是否继续？`)) return;
  beginValidationBatchUI(ids.length, label);
  const rows = [];
  let cancelled = false;
  try {
    for (let i = 0; i < ids.length; i++) {
      if (state.validationBatchCancelled) break;
      await waitWhileValidationPaused();
      if (state.validationBatchCancelled) break;
      if (meta) meta.textContent = `验证中 ${i + 1} / ${ids.length} …`;
      startValidationSegmentProgress(i, ids.length, label);
      try {
        const data = await runValidationPipelineRow(ids[i], { skipRefresh: true });
        stopValidationSegmentProgress();
        const pp = data.proposed_patch && typeof data.proposed_patch === "object" ? data.proposed_patch : {};
        rows.push({
          candidateId: ids[i],
          ok: true,
          data,
          proposed_patch: Object.keys(pp).length ? pp : null,
        });
        setValidationBatchProgressDeterministic(rows.length, ids.length, label);
      } catch (e) {
        stopValidationSegmentProgress();
        rows.push({ candidateId: ids[i], ok: false, error: e.message });
        setValidationBatchProgressDeterministic(rows.length, ids.length, label);
      }
    }
    cancelled = !!state.validationBatchCancelled;
  } finally {
    endValidationBatchUI(rows.length, ids.length, label, cancelled);
  }
  state.lastValidationBatch = { mode, rows, cancelled };
  if (meta) {
    meta.textContent = cancelled
      ? `已取消 · 已处理 ${rows.length} / ${ids.length} 条，见弹窗`
      : `「${label}」完成，见弹窗`;
  }
  appendClientLog(
    `[UI] validation pipeline batch mode=${mode} total=${ids.length} done=${rows.length} cancelled=${cancelled}`,
  );
  showValidationResultModal();
  await refreshValidationRegionCandidates();
}

async function promoteValidationRegionCandidatesToFinal() {
  const laneEl = qs("validation-region-lane-select");
  const laneVal = laneEl ? laneEl.value : "local";
  const granEl = qs("validation-promote-granularity");
  const granularity = granEl ? granEl.value : "all";
  const ids = state.validationRegionCandidates.map((r) => r.id).filter(Boolean);
  const meta = qs("validation-region-meta");
  if (!ids.length) {
    alert("请先点击「从数据库刷新」加载候选。");
    return;
  }
  const granLabel =
    granularity === "all" ? "全部颗粒度（写入顺序 major→sub→allen）" : `仅颗粒度「${granularity}」`;
  if (
    !window.confirm(
      `将对当前列表共 ${ids.length} 条尝试晋升到正式库：${granLabel}。\n\n前提：已「入未验证库」，且在验证与提升中心对未验证记录执行规则校验且通过；不符合的条将跳过。\n\n是否继续？`,
    )
  ) {
    return;
  }
  if (meta) meta.textContent = "正在按颗粒度晋升到正式库…";
  try {
    const res = await api("/api/region-candidates/promote-to-final", {
      method: "POST",
      body: JSON.stringify({
        lane: laneVal,
        granularity,
        candidate_ids: ids,
        reviewer: "user",
      }),
    });
    const sum = res.summary || {};
    const sk = (res.skipped || []).length;
    appendClientLog(
      `[PROMOTE] validation_center to_final granularity=${granularity} ok=${sum.success_count ?? 0}/${sum.total ?? 0} skipped=${sk}`,
    );
    alert(
      `完成。写入成功 ${sum.success_count ?? 0} / ${sum.total ?? 0}；跳过 ${sk} 条（未入未验证库、未校验通过或已晋升等）。详情见日志。`,
    );
    await refreshValidationRegionCandidates();
  } catch (err) {
    appendClientLog(`[ERROR] promote to final reason=${err.message}`, "error");
    alert(err.message);
    if (meta) meta.textContent = `晋升失败: ${err.message}`;
  }
}

async function refreshFinalCircuits() {
  const meta = qs("final-circuit-meta");
  const tbody = document.querySelector("#final-circuit-table tbody");
  if (!tbody) return;
  const fileId = (qs("final-circuit-file-select") && qs("final-circuit-file-select").value) || state.selectedFileId || "";
  tbody.innerHTML = "";
  try {
    const data = await api(`/api/final/circuits?file_id=${encodeURIComponent(fileId)}&limit=500`);
    const items = data.items || [];
    const warn = (data.warnings || []).filter(Boolean);
    if (meta) {
      const bits = [`共 ${items.length} 条（生产库终表）`];
      if (warn.length) bits.push(`警告: ${warn.join("；")}`);
      meta.textContent = bits.join(" · ");
    }
    items.forEach((row) => {
      const idCol = row._id_column || "id";
      const pk = row[idCol];
      const kind = pickRowField(row, ["circuit_kind", "kind", "circuit_kind_candidate"]);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(row._final_granularity)}</td>
        <td>${escapeHtml(row._final_table)}</td>
        <td>${escapeHtml(pk)}</td>
        <td>${escapeHtml(row.circuit_code)}</td>
        <td>${escapeHtml(row.en_name)}</td>
        <td>${escapeHtml(row.cn_name)}</td>
        <td>${escapeHtml(kind)}</td>
        <td>${escapeHtml(row.data_source)}</td>
        <td>${escapeHtml(row.updated_at || row.created_at || "")}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    if (meta) meta.textContent = `加载失败: ${err.message}`;
  }
}

async function refreshFinalConnections() {
  const meta = qs("final-connection-meta");
  const tbody = document.querySelector("#final-connection-table tbody");
  if (!tbody) return;
  const fileId = (qs("final-connection-file-select") && qs("final-connection-file-select").value) || state.selectedFileId || "";
  tbody.innerHTML = "";
  try {
    const data = await api(`/api/final/connections?file_id=${encodeURIComponent(fileId)}&limit=500`);
    const items = data.items || [];
    const warn = (data.warnings || []).filter(Boolean);
    if (meta) {
      const bits = [`共 ${items.length} 条（生产库终表）`];
      if (warn.length) bits.push(`警告: ${warn.join("；")}`);
      meta.textContent = bits.join(" · ");
    }
    items.forEach((row) => {
      const idCol = row._id_column || "id";
      const pk = row[idCol];
      const modality = pickRowField(row, ["connection_modality", "modality"]);
      const src = pickRowField(row, [
        "source_major_region_id",
        "source_sub_region_id",
        "source_allen_region_id",
        "source_region_ref",
        "source_region",
      ]);
      const tgt = pickRowField(row, [
        "target_major_region_id",
        "target_sub_region_id",
        "target_allen_region_id",
        "target_region_ref",
        "target_region",
      ]);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(row._final_granularity)}</td>
        <td>${escapeHtml(row._final_table)}</td>
        <td>${escapeHtml(pk)}</td>
        <td>${escapeHtml(row.connection_code)}</td>
        <td>${escapeHtml(row.en_name)}</td>
        <td>${escapeHtml(row.cn_name)}</td>
        <td>${escapeHtml(modality)}</td>
        <td>${escapeHtml(src)}</td>
        <td>${escapeHtml(tgt)}</td>
        <td>${escapeHtml(row.data_source)}</td>
        <td>${escapeHtml(row.updated_at || row.created_at || "")}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    if (meta) meta.textContent = `加载失败: ${err.message}`;
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
  syncOntologyStatusHint(payload.status.ontology_rules);
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
  const payload = await api(`/api/files/${state.selectedFileId}/region-candidates?lane=all`);
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

async function refreshReviewDataForActiveTab() {
  const t = state.activeTab;
  if (t === "tab-review-region") {
    await refreshCandidates();
  } else if (t === "tab-review-circuit") {
    await refreshCircuitCandidates();
  } else if (t === "tab-review-connection") {
    await refreshConnectionCandidates();
  } else if (t === "tab-validation-region") {
    await refreshValidationRegionCandidates();
  } else if (t === "tab-validation-circuit") {
    await refreshFinalCircuits();
  } else if (t === "tab-validation-connection") {
    await refreshFinalConnections();
  }
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
  await refreshReviewDataForActiveTab();
  await refreshUnverified(fileId);
  await refreshUnverifiedCircuits(fileId);
  await refreshUnverifiedConnections(fileId);
  await refreshRegionVersions();
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
      let profileKey = "";
      let deepseekOverride = undefined;
      if (mode === "deepseek" || mode === "multi") {
        const cfg = await openDeepseekRegionModal("file");
        if (!cfg) return;
        profileKey = cfg.profile_key || "";
        deepseekOverride = cfg.deepseek_override;
      }
      const body = { mode };
      if (profileKey) body.profile_key = profileKey;
      if (deepseekOverride && Object.keys(deepseekOverride).length) body.deepseek_override = deepseekOverride;
      const exRes = await api(`/api/files/${fileId}/extract-regions`, { method: "POST", body: JSON.stringify(body) });
      notifyRegionDuplicateHint(exRes);
      appendClientLog(`[EXTRACT] region_extract triggered file_id=${fileId} mode=${mode}`);
    }
    await bootstrap();
  } catch (err) {
    appendClientLog(`[ERROR] action=${action} file_id=${fileId} reason=${err.message}`, "error");
    alert(`操作失败: ${err.message}`);
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
    moonshot: {
      enabled: qs("cfg-moonshot-enabled")?.checked || false,
      api_key: qs("cfg-moonshot-key")?.value || "",
      base_url: (qs("cfg-moonshot-base")?.value || "").trim(),
      model: (qs("cfg-moonshot-model")?.value || "").trim(),
      temperature: Number(qs("cfg-moonshot-temperature")?.value || 0.2),
    },
    pipeline: {
      normalize_mode_default: qs("cfg-normalize-mode").value,
      validate_mode_default: qs("cfg-validate-mode").value,
      auto_validate_on_extract: qs("cfg-auto-validate-on-extract")?.checked || false,
      ontology_rules: {
        enabled: qs("cfg-ontology-enabled")?.checked || false,
        path: (qs("cfg-ontology-path")?.value || "").trim(),
        stage_policy: qs("cfg-ontology-stage-policy")?.value || "warn",
      },
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

/** 保存脑区候选；409 时带 duplicate_conflict，不抛错以便弹窗处理 */
async function saveRegionCandidatePatch(id, patch, duplicateResolution) {
  const body = { patch, reviewer: "user" };
  if (duplicateResolution) body.duplicate_resolution = duplicateResolution;
  const resp = await fetch(`/api/candidates/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { ok: false, error: text };
  }
  if (resp.status === 409 && data.duplicate_conflict) {
    return { ok: false, duplicate_conflict: data.duplicate_conflict, error: data.error };
  }
  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || `HTTP_${resp.status}`);
  }
  return { ok: true, ...data };
}

function openRegionDuplicateSaveModal(dc) {
  return new Promise((resolve) => {
    const backdrop = qs("modal-region-dup-save");
    const msg = qs("modal-region-dup-save-msg");
    const detail = qs("modal-region-dup-save-detail");
    if (!backdrop || !msg) {
      resolve("cancel");
      return;
    }
    const n = (dc.conflicting_ids && dc.conflicting_ids.length) || 0;
    msg.textContent = `与 ${n} 条已有候选的 EN/CN 相同（英文小写 + 中文），请选择如何处理。`;
    const en = dc.en || "—";
    const cn = dc.cn || "—";
    const ids = (dc.conflicting_ids || []).slice(0, 8).join("\n");
    detail.textContent = `当前名称：EN「${en}」 CN「${cn}」\n冲突候选 id（共 ${n} 条）：\n${ids}${n > 8 ? "\n…" : ""}`;
    backdrop.hidden = false;
    const bReplace = qs("btn-region-dup-replace");
    const bKeep = qs("btn-region-dup-keep");
    const bCancel = qs("btn-region-dup-cancel");
    const cleanup = () => {
      backdrop.hidden = true;
      if (bReplace) bReplace.onclick = null;
      if (bKeep) bKeep.onclick = null;
      if (bCancel) bCancel.onclick = null;
    };
    const done = (v) => {
      cleanup();
      resolve(v);
    };
    if (bReplace) bReplace.onclick = () => done("replace");
    if (bKeep) bKeep.onclick = () => done("keep");
    if (bCancel) bCancel.onclick = () => done("cancel");
  });
}

async function resolveDuplicateAndSave(id, patch) {
  let r = await saveRegionCandidatePatch(id, patch, null);
  if (r.ok) return r;
  if (!r.duplicate_conflict) throw new Error(r.error || "save_failed");
  const choice = await openRegionDuplicateSaveModal(r.duplicate_conflict);
  if (choice === "cancel") return { ok: false, cancelled: true };
  const mode = choice === "replace" ? "replace_others" : "keep_duplicates";
  r = await saveRegionCandidatePatch(id, patch, mode);
  if (!r.ok) {
    if (r.duplicate_conflict) throw new Error("仍然冲突，请刷新后重试");
    throw new Error(r.error || "save_failed");
  }
  return r;
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
  const id = qs("review-id")?.value;
  if (!id) {
    appendClientLog("[REVIEW] 保存跳过：未选中候选", "warn");
    return;
  }
  const nextId = getNextRegionCandidateIdAfterCurrent(id);
  const patch = currentCandidatePatch();
  const r = await resolveDuplicateAndSave(id, patch);
  if (r.cancelled) return;
  appendClientLog(`[REVIEW] edit candidate_id=${id}`);
  await refreshRegionReviewAfterSaveAndSelect(nextId);
}

/** 仅写入修改并刷新当前行展示，不跳转（供「审核通过/驳回」先保存再审核） */
async function saveCandidateEditWithoutNavigate() {
  const id = qs("review-id")?.value;
  if (!id) return false;
  const patch = currentCandidatePatch();
  const r = await resolveDuplicateAndSave(id, patch);
  if (r.cancelled) return false;
  appendClientLog(`[REVIEW] edit candidate_id=${id}`);
  await refreshCandidates();
  renderInspector();
  return true;
}

async function saveCircuitCandidateEdit() {
  const id = qs("c-review-id")?.value;
  if (!id) {
    appendClientLog("[REVIEW] 回路保存跳过：未选中候选", "warn");
    return;
  }
  const nextId = getNextCircuitCandidateIdAfterCurrent(id);
  await api(`/api/circuit-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentCircuitPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit circuit_candidate_id=${id}`);
  await refreshCircuitReviewAfterSaveAndSelect(nextId);
}

async function saveCircuitCandidateEditWithoutNavigate() {
  const id = qs("c-review-id")?.value;
  if (!id) return false;
  await api(`/api/circuit-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentCircuitPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit circuit_candidate_id=${id}`);
  await refreshCircuitCandidates();
  renderInspector();
  return true;
}

/** 仅调用审核 API，不刷新全局（由调用方设置选中并刷新） */
async function reviewCandidateOnly(action) {
  const id = qs("review-id")?.value;
  if (!id) throw new Error("未选中候选");
  await api(`/api/candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} candidate_id=${id}`);
}

async function reviewCandidate(action) {
  const id = qs("review-id")?.value;
  if (!id) return;
  const nextId = getNextRegionCandidateIdAfterCurrent(id);
  await reviewCandidateOnly(action);
  await refreshRegionReviewAfterSaveAndSelect(nextId);
}

async function reviewCircuitCandidateOnly(action) {
  const id = qs("c-review-id")?.value;
  if (!id) throw new Error("未选中回路候选");
  await api(`/api/circuit-candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("c-review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} circuit_candidate_id=${id}`);
}

async function reviewCircuitCandidate(action) {
  const id = qs("c-review-id")?.value;
  if (!id) return;
  const nextId = getNextCircuitCandidateIdAfterCurrent(id);
  await reviewCircuitCandidateOnly(action);
  await refreshCircuitReviewAfterSaveAndSelect(nextId);
}

async function runRegionExtractFile() {
  const fileId = qs("extract-file-select").value || state.selectedFileId;
  const mode = qs("extract-mode-select").value || "local";
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  let profileKey = "";
  let deepseekOverride = undefined;
  if (mode === "deepseek" || mode === "multi") {
    const cfg = await openDeepseekRegionModal("file");
    if (!cfg) return;
    profileKey = cfg.profile_key || "";
    deepseekOverride = cfg.deepseek_override;
  }
  const body = { mode };
  if (profileKey) body.profile_key = profileKey;
  if (deepseekOverride && Object.keys(deepseekOverride).length) body.deepseek_override = deepseekOverride;

  const res = await withRegionProgress(`文件抽取 · ${mode}`, () =>
    api(`/api/files/${fileId}/extract-regions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
  state.selectedFileId = fileId;
  if (qs("extract-file-select")) qs("extract-file-select").value = fileId;
  if (res.version_id) {
    state.regionSelectedVersionId = res.version_id;
    state.reviewSnapshotVersionId = res.version_id;
  }
  notifyRegionDuplicateHint(res);
  appendClientLog(`[EXTRACT] file file_id=${fileId} mode=${mode} version=${res.version_id || "-"}`);
  await bootstrap();
  await refreshRegionVersions();
}

async function runRegionExtractText() {
  const fileId = qs("extract-file-select").value || state.selectedFileId;
  const mode = qs("region-text-mode-select").value || "local";
  const text = (qs("region-text-input").value || "").trim();
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  if (!text) {
    alert("请输入文本");
    return;
  }
  let profileKey = "";
  let deepseekOverride = undefined;
  if (mode === "deepseek" || mode === "multi") {
    const cfg = await openDeepseekRegionModal("text");
    if (!cfg) return;
    profileKey = cfg.profile_key || "";
    deepseekOverride = cfg.deepseek_override;
  }
  const body = { text, mode, file_id: fileId };
  if (profileKey) body.profile_key = profileKey;
  if (deepseekOverride && Object.keys(deepseekOverride).length) body.deepseek_override = deepseekOverride;

  const res = await withRegionProgress(`文本抽取 · ${mode}`, () =>
    api("/api/generate/regions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
  state.selectedFileId = fileId;
  if (qs("extract-file-select")) qs("extract-file-select").value = fileId;
  if (res.version_id) {
    state.regionSelectedVersionId = res.version_id;
    state.reviewSnapshotVersionId = res.version_id;
  }
  notifyRegionDuplicateHint(res);
  appendClientLog(`[EXTRACT] text file_id=${fileId} mode=${mode}`);
  await bootstrap();
  await refreshRegionVersions();
}

async function runRegionExtractDirect() {
  const fileId = qs("extract-file-select").value || state.selectedFileId;
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  const cfg = await openDeepseekRegionModal("direct");
  if (!cfg) return;
  const profileKey = cfg.profile_key || "";
  const deepseekOverride = cfg.deepseek_override;

  const params = {
    topic: (qs("region-direct-topic").value || "脑区").trim(),
    species: (qs("region-direct-species").value || "人类").trim(),
    granularity: (qs("region-direct-granularity").value || "major").trim(),
    extra_instructions: (qs("region-direct-extra").value || "").trim(),
  };
  const body = { params, file_id: fileId };
  if (profileKey) body.profile_key = profileKey;
  if (deepseekOverride && Object.keys(deepseekOverride).length) body.deepseek_override = deepseekOverride;

  const res = await withRegionProgress("DeepSeek 直接生成", () =>
    api("/api/generate/regions-direct", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
  state.selectedFileId = fileId;
  if (qs("extract-file-select")) qs("extract-file-select").value = fileId;
  if (res.version_id) {
    state.regionSelectedVersionId = res.version_id;
    state.reviewSnapshotVersionId = res.version_id;
  }
  notifyRegionDuplicateHint(res);
  appendClientLog(`[EXTRACT] direct file_id=${fileId}`);
  await bootstrap();
  await refreshRegionVersions();
}

async function runRegionExtractDirectKimi() {
  const fileId = qs("extract-file-select").value || state.selectedFileId;
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  const params = {
    topic: (qs("region-direct-topic").value || "脑区").trim(),
    species: (qs("region-direct-species").value || "人类").trim(),
    granularity: (qs("region-direct-granularity").value || "major").trim(),
    extra_instructions: (qs("region-direct-extra").value || "").trim(),
  };
  const body = { params, file_id: fileId, provider: "kimi" };

  const res = await withRegionProgress("Kimi 直接生成", () =>
    api("/api/generate/regions-direct", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
  state.selectedFileId = fileId;
  if (qs("extract-file-select")) qs("extract-file-select").value = fileId;
  if (res.version_id) {
    state.regionSelectedVersionId = res.version_id;
    state.reviewSnapshotVersionId = res.version_id;
  }
  notifyRegionDuplicateHint(res);
  appendClientLog(`[EXTRACT] direct_kimi file_id=${fileId}`);
  await bootstrap();
  await refreshRegionVersions();
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

async function commitApprovedRegions(candidateIds) {
  if (!state.selectedFileId) return;
  const body = { reviewer: "user" };
  if (candidateIds != null && candidateIds.length) {
    body.candidate_ids = candidateIds;
  }
  const res = await api(`/api/files/${state.selectedFileId}/commit-regions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  state.lastCommitResult = res;
  if (qs("commit-result")) qs("commit-result").textContent = pretty(res);
  appendClientLog(`[UNVERIFIED] stage_from_candidates file_id=${state.selectedFileId}`);
  await refreshUnverified(state.selectedFileId);
  renderInspector();
  await bootstrap();
}

async function applyRegionSnapshotToCandidates() {
  const fileId = state.selectedFileId || (qs("extract-file-select") && qs("extract-file-select").value) || "";
  const vid = state.regionSelectedVersionId;
  if (!fileId) {
    alert("请先选择文件");
    return;
  }
  if (!vid) {
    alert("暂无快照，请先完成抽取或在「历史版本」中选择一条");
    return;
  }
  const res = await api(`/api/files/${fileId}/region-candidates/from-version`, {
    method: "POST",
    body: JSON.stringify({ version_id: vid }),
  });
  notifyRegionDuplicateHint(res);
  appendClientLog(`[REVIEW] snapshot→candidates version_id=${vid} count=${res.count ?? "-"}`);
  await refreshCandidates();
}

function openRegionReviewTab() {
  setActiveTab("tab-review-region");
  refreshCandidates().catch(() => {});
}

async function batchReviewRegionCandidates(action) {
  const ids = [...state.reviewBatchIds];
  if (!ids.length) {
    alert("请先勾选要操作的候选");
    return;
  }
  let note = "";
  if (action === "reject") {
    note = prompt("驳回说明（可选，将写入每条审核备注）", "") || "";
  } else {
    note = prompt("通过说明（可选）", "") || "";
  }
  const res = await api("/api/candidates/batch-review", {
    method: "POST",
    body: JSON.stringify({ candidate_ids: ids, action, reviewer: "user", note }),
  });
  appendClientLog(
    `[REVIEW] batch_${action} ok=${res.updated ?? 0} failed=${res.failed_count ?? 0}`,
    res.failed_count ? "error" : "info",
  );
  if (res.failed_count) {
    alert(`部分失败：成功 ${res.updated}，失败 ${res.failed_count}。详见控制台日志。`);
  }
  state.reviewBatchIds.clear();
  await bootstrap();
}

async function batchStageSelectedReviewedRegions() {
  const ids = [...state.reviewBatchIds];
  if (!ids.length) {
    alert("请先勾选要入未验证库的候选（须已为「审核通过」状态）");
    return;
  }
  await commitApprovedRegions(ids);
  state.reviewBatchIds.clear();
  renderCandidateTable();
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
  const id = qs("conn-review-id")?.value;
  if (!id) {
    appendClientLog("[REVIEW] 连接保存跳过：未选中候选", "warn");
    return;
  }
  const nextId = getNextConnectionCandidateIdAfterCurrent(id);
  await api(`/api/connection-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentConnectionPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit connection_candidate_id=${id}`);
  await refreshConnectionReviewAfterSaveAndSelect(nextId);
}

async function saveConnectionCandidateEditWithoutNavigate() {
  const id = qs("conn-review-id")?.value;
  if (!id) return false;
  await api(`/api/connection-candidates/${id}`, {
    method: "POST",
    body: JSON.stringify({ patch: currentConnectionPatch(), reviewer: "user" }),
  });
  appendClientLog(`[REVIEW] edit connection_candidate_id=${id}`);
  await refreshConnectionCandidates();
  renderInspector();
  return true;
}

async function reviewConnectionCandidateOnly(action) {
  const id = qs("conn-review-id")?.value;
  if (!id) throw new Error("未选中连接候选");
  await api(`/api/connection-candidates/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer: "user", note: qs("conn-review-note").value.trim() }),
  });
  appendClientLog(`[REVIEW] ${action} connection_candidate_id=${id}`);
}

async function reviewConnectionCandidate(action) {
  const id = qs("conn-review-id")?.value;
  if (!id) return;
  const nextId = getNextConnectionCandidateIdAfterCurrent(id);
  await reviewConnectionCandidateOnly(action);
  await refreshConnectionReviewAfterSaveAndSelect(nextId);
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

function migrateSnapshotTabId(tabId) {
  if (tabId === "tab-extraction") return "tab-extract-region";
  if (tabId === "tab-review") return "tab-review-region";
  return tabId;
}

async function restoreSnapshot() {
  try {
    const payload = await api("/api/workbench/snapshot");
    const ss = payload.snapshot || {};
    if (ss.active_tab) setActiveTab(migrateSnapshotTabId(ss.active_tab));
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

  qs("btn-rules-refresh")?.addEventListener("click", async () => {
    try {
      await refreshRulesCenter();
      appendClientLog("[UI] rules center refreshed");
    } catch (err) {
      appendClientLog(`[ERROR] rules refresh failed reason=${err.message}`, "error");
      alert(`刷新规则失败: ${err.message}`);
    }
  });

  qs("btn-rules-toggle-raw")?.addEventListener("click", () => {
    const w = qs("rules-raw-wrap");
    if (!w) return;
    w.hidden = !w.hidden;
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
      alert(`上传失败: ${err.message}`);
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

  qs("extract-file-select").addEventListener("change", async (evt) => {
    const fileId = evt.target.value;
    if (fileId) {
      await selectFile(fileId);
    }
  });

  const vrl = qs("validation-region-lane-select");
  if (vrl) {
    vrl.addEventListener("change", async () => {
      if (state.activeTab === "tab-validation-region") await refreshValidationRegionCandidates();
    });
  }
  const fcs = qs("final-circuit-file-select");
  if (fcs) {
    fcs.addEventListener("change", async () => {
      if (state.activeTab === "tab-validation-circuit") await refreshFinalCircuits();
    });
  }
  const fns = qs("final-connection-file-select");
  if (fns) {
    fns.addEventListener("change", async () => {
      if (state.activeTab === "tab-validation-connection") await refreshFinalConnections();
    });
  }
  qs("btn-validation-region-refresh")?.addEventListener("click", async () => {
    try {
      await refreshValidationRegionCandidates();
    } catch (err) {
      appendClientLog(`[ERROR] validation region refresh reason=${err.message}`, "error");
    }
  });
  qs("btn-validation-promote-final")?.addEventListener("click", async () => {
    try {
      await promoteValidationRegionCandidatesToFinal();
    } catch (err) {
      appendClientLog(`[ERROR] validation promote final reason=${err.message}`, "error");
      alert(err.message);
    }
  });

  const vrTbody = document.querySelector("#validation-region-table tbody");
  if (vrTbody) {
    vrTbody.addEventListener("click", async (evt) => {
      const btn = evt.target.closest("button[data-vr-action]");
      if (!btn || btn.dataset.vrAction !== "save") return;
      const tr = btn.closest("tr");
      const id = tr && tr.dataset.candidateId;
      if (!id) return;
      try {
        await saveValidationRegionRow(id, tr);
      } catch (err) {
        appendClientLog(`[ERROR] validation center save reason=${err.message}`, "error");
        alert(err.message);
      }
    });
  }

  document.querySelectorAll(".validation-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const m = btn.dataset.validationMode;
      if (m) setValidationCenterMode(m);
    });
  });

  qs("btn-validation-exec-local")?.addEventListener("click", async () => {
    try {
      setValidationCenterMode("local");
      await runValidationBatch();
    } catch (err) {
      appendClientLog(`[ERROR] validation batch local reason=${err.message}`, "error");
      alert(err.message);
    }
  });
  qs("btn-validation-exec-deepseek")?.addEventListener("click", async () => {
    try {
      setValidationCenterMode("deepseek");
      await runValidationBatch();
    } catch (err) {
      appendClientLog(`[ERROR] validation batch deepseek reason=${err.message}`, "error");
      alert(err.message);
    }
  });
  qs("btn-validation-exec-multi")?.addEventListener("click", async () => {
    try {
      setValidationCenterMode("multi");
      await runValidationBatch();
    } catch (err) {
      appendClientLog(`[ERROR] validation batch multi reason=${err.message}`, "error");
      alert(err.message);
    }
  });

  qs("btn-validation-batch-pause")?.addEventListener("click", () => {
    if (!state.validationBatchRunning) return;
    state.validationBatchPaused = !state.validationBatchPaused;
    const btn = qs("btn-validation-batch-pause");
    if (btn) btn.textContent = state.validationBatchPaused ? "继续" : "暂停";
  });
  qs("btn-validation-batch-cancel")?.addEventListener("click", () => {
    if (!state.validationBatchRunning) return;
    state.validationBatchCancelled = true;
    state.validationBatchPaused = false;
    appendClientLog("[UI] validation batch cancel requested", "info");
  });

  qs("btn-modal-validation-close")?.addEventListener("click", () => closeValidationResultModal());
  qs("modal-validation-result")?.addEventListener("click", (evt) => {
    if (evt.target.id === "modal-validation-result") closeValidationResultModal();
  });
  qs("btn-modal-validation-apply")?.addEventListener("click", async () => {
    try {
      await applyPendingValidationSuggestions();
    } catch (err) {
      appendClientLog(`[ERROR] apply suggestions reason=${err.message}`, "error");
      alert(err.message);
    }
  });
  qs("btn-final-circuit-refresh")?.addEventListener("click", async () => {
    try {
      await refreshFinalCircuits();
    } catch (err) {
      appendClientLog(`[ERROR] final circuits refresh reason=${err.message}`, "error");
    }
  });
  qs("btn-final-connection-refresh")?.addEventListener("click", async () => {
    try {
      await refreshFinalConnections();
    } catch (err) {
      appendClientLog(`[ERROR] final connections refresh reason=${err.message}`, "error");
    }
  });

  document.querySelectorAll(".region-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => setRegionExtractMode(btn.dataset.regionMode));
  });

  const brf = qs("btn-region-run-file");
  if (brf) {
    brf.addEventListener("click", async () => {
      try {
        await runRegionExtractFile();
      } catch (err) {
        appendClientLog(`[ERROR] extract failed reason=${err.message}`, "error");
        alert(`抽取失败: ${err.message}`);
      }
    });
  }

  const brt = qs("btn-region-run-text");
  if (brt) {
    brt.addEventListener("click", async () => {
      try {
        await runRegionExtractText();
      } catch (err) {
        appendClientLog(`[ERROR] text extract failed reason=${err.message}`, "error");
        alert(`文本抽取失败: ${err.message}`);
      }
    });
  }

  const brd = qs("btn-region-run-direct");
  if (brd) {
    brd.addEventListener("click", async () => {
      try {
        await runRegionExtractDirect();
      } catch (err) {
        appendClientLog(`[ERROR] direct generate failed reason=${err.message}`, "error");
        alert(`直接生成失败: ${err.message}`);
      }
    });
  }

  const brdk = qs("btn-region-run-direct-kimi");
  if (brdk) {
    brdk.addEventListener("click", async () => {
      try {
        await runRegionExtractDirectKimi();
      } catch (err) {
        appendClientLog(`[ERROR] kimi direct generate failed reason=${err.message}`, "error");
        alert(`Kimi 直接生成失败: ${err.message}`);
      }
    });
  }

  const brv = qs("btn-region-version-refresh");
  if (brv) {
    brv.addEventListener("click", async () => {
      try {
        await refreshRegionVersions();
      } catch (err) {
        appendClientLog(`[ERROR] version list failed reason=${err.message}`, "error");
      }
    });
  }

  async function handleExtractRegionVersionSelectChange(evt) {
    state.regionSelectedVersionId = evt.target.value;
    updateRegionVersionMeta();
    try {
      await loadExtractRegionVersionTable(state.regionSelectedVersionId);
    } catch (err) {
      appendClientLog(`[ERROR] load extract version failed reason=${err.message}`, "error");
    }
  }

  async function handleReviewRegionVersionSelectChange(evt) {
    state.reviewSnapshotVersionId = evt.target.value;
    updateRegionVersionMeta();
    try {
      await loadReviewSnapshotVersionTable(state.reviewSnapshotVersionId);
    } catch (err) {
      appendClientLog(`[ERROR] load review snapshot failed reason=${err.message}`, "error");
    }
  }

  const regionVerSel = qs("region-version-select");
  if (regionVerSel) {
    regionVerSel.addEventListener("change", handleExtractRegionVersionSelectChange);
  }

  const reviewVerSel = qs("review-region-version-select");
  if (reviewVerSel) {
    reviewVerSel.addEventListener("change", handleReviewRegionVersionSelectChange);
  }

  const brSnap = qs("btn-review-snapshot-refresh");
  if (brSnap) {
    brSnap.addEventListener("click", async () => {
      try {
        await refreshRegionVersions();
      } catch (err) {
        appendClientLog(`[ERROR] review snapshot refresh reason=${err.message}`, "error");
      }
    });
  }

  const brvd = qs("btn-region-version-delete");
  if (brvd) {
    brvd.addEventListener("click", async () => {
      try {
        await deleteSelectedRegionVersion();
      } catch (err) {
        appendClientLog(`[ERROR] delete snapshot failed reason=${err.message}`, "error");
        alert(`删除失败: ${err.message}`);
      }
    });
  }

  const bSyncCand = qs("btn-region-sync-to-candidates");
  if (bSyncCand) {
    bSyncCand.addEventListener("click", async () => {
      try {
        await applyRegionSnapshotToCandidates();
      } catch (err) {
        appendClientLog(`[ERROR] sync snapshot reason=${err.message}`, "error");
        alert(`同步失败: ${err.message}`);
      }
    });
  }
  const bOpenReview = qs("btn-region-open-review");
  if (bOpenReview) {
    bOpenReview.addEventListener("click", () => {
      openRegionReviewTab();
    });
  }

  setRegionExtractMode(state.regionExtractSubMode || "file");

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

  const candidateTableTbody = document.querySelector("#candidate-table tbody");
  if (candidateTableTbody) {
    candidateTableTbody.addEventListener("change", (evt) => {
      const cb = evt.target.closest("input.review-cb");
      if (!cb) return;
      const id = cb.dataset.candidateId;
      if (cb.checked) state.reviewBatchIds.add(id);
      else state.reviewBatchIds.delete(id);
      syncReviewSelectAllCheckbox();
    });

    candidateTableTbody.addEventListener("click", (evt) => {
      if (evt.target.closest("input.review-cb")) return;
      if (evt.target.closest("input[type=checkbox]")) return;
      const row = evt.target.closest("tr[data-candidate-id]");
      if (!row) return;
      state.selectedCandidateId = row.dataset.candidateId;
      renderCandidateTable();
      fillCandidateEditor(state.candidates.find((it) => it.id === state.selectedCandidateId));
      renderInspector();
    });
  }

  const reviewSnapTbody = document.querySelector("#review-snapshot-table tbody");
  if (reviewSnapTbody) {
    reviewSnapTbody.addEventListener("click", (evt) => {
      const tr = evt.target.closest("tr[data-candidate-id]");
      if (!tr) return;
      const cid = tr.dataset.candidateId;
      if (!cid) return;
      const found = state.candidates.find((c) => c.id === cid);
      if (found) {
        state.selectedCandidateId = cid;
        pickSnapshotRowForReview(cid);
        renderCandidateTable();
        fillCandidateEditor(found);
        renderInspector();
      } else {
        appendClientLog(`[REVIEW] 快照行在当前候选列表中无对应 id=${cid}`, "info");
      }
    });
  }

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

  // 审核过滤（下拉 change 即时生效；「应用过滤」等同刷新一次）
  const filterStatus = qs("review-filter-status");
  const filterMethod = qs("review-filter-method");
  if (filterStatus) {
    filterStatus.addEventListener("change", () => applyReviewFiltersFromDom());
  }
  if (filterMethod) {
    filterMethod.addEventListener("change", () => applyReviewFiltersFromDom());
  }
  const filterApply = qs("btn-review-filter-apply");
  const filterClear = qs("btn-review-filter-clear");
  if (filterApply) {
    filterApply.addEventListener("click", () => applyReviewFiltersFromDom());
  }
  if (filterClear) {
    filterClear.addEventListener("click", () => {
      state.reviewBatchIds.clear();
      _reviewFilter.status = "";
      _reviewFilter.method = "";
      if (qs("review-filter-status")) qs("review-filter-status").value = "";
      if (qs("review-filter-method")) qs("review-filter-method").value = "";
      renderCandidateTable();
    });
  }

  const btnToggleSnap = qs("btn-toggle-review-snapshot");
  const splitWrap = qs("review-region-split");
  if (btnToggleSnap && splitWrap) {
    btnToggleSnap.addEventListener("click", () => {
      const collapsed = splitWrap.classList.toggle("snapshot-collapsed");
      btnToggleSnap.textContent = collapsed ? "展开" : "收起";
      btnToggleSnap.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
  }

  const rsa = qs("review-select-all");
  if (rsa) {
    rsa.addEventListener("change", () => {
      const rows = getFilteredCandidateRows();
      const on = rsa.checked;
      if (on) rows.forEach((r) => state.reviewBatchIds.add(r.id));
      else rows.forEach((r) => state.reviewBatchIds.delete(r.id));
      renderCandidateTable();
    });
  }

  const brApprove = qs("btn-review-batch-approve");
  if (brApprove) {
    brApprove.addEventListener("click", async () => {
      try {
        await batchReviewRegionCandidates("approve");
      } catch (err) {
        appendClientLog(`[ERROR] batch approve reason=${err.message}`, "error");
        alert(`批量通过失败: ${err.message}`);
      }
    });
  }
  const brReject = qs("btn-review-batch-reject");
  if (brReject) {
    brReject.addEventListener("click", async () => {
      try {
        await batchReviewRegionCandidates("reject");
      } catch (err) {
        appendClientLog(`[ERROR] batch reject reason=${err.message}`, "error");
        alert(`批量驳回失败: ${err.message}`);
      }
    });
  }
  const brStage = qs("btn-review-batch-stage");
  if (brStage) {
    brStage.addEventListener("click", async () => {
      try {
        await batchStageSelectedReviewedRegions();
      } catch (err) {
        appendClientLog(`[ERROR] batch stage reason=${err.message}`, "error");
      }
    });
  }

  qs("btn-review-save")?.addEventListener("click", async () => {
    try {
      await saveCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] candidate save failed reason=${err.message}`, "error");
      alert(`保存失败: ${err.message}`);
    }
  });

  qs("btn-review-approve")?.addEventListener("click", async () => {
    try {
      const id = qs("review-id")?.value;
      if (!id) {
        alert("请先选择候选");
        return;
      }
      const nextId = getNextRegionCandidateIdAfterCurrent(id);
      const saved = await saveCandidateEditWithoutNavigate();
      if (!saved) return;
      await reviewCandidateOnly("approve");
      await refreshRegionReviewAfterSaveAndSelect(nextId);
    } catch (err) {
      appendClientLog(`[ERROR] approve failed reason=${err.message}`, "error");
      alert(`审核通过失败: ${err.message}`);
    }
  });

  qs("btn-review-reject")?.addEventListener("click", async () => {
    try {
      const id = qs("review-id")?.value;
      if (!id) {
        alert("请先选择候选");
        return;
      }
      const nextId = getNextRegionCandidateIdAfterCurrent(id);
      const saved = await saveCandidateEditWithoutNavigate();
      if (!saved) return;
      await reviewCandidateOnly("reject");
      await refreshRegionReviewAfterSaveAndSelect(nextId);
    } catch (err) {
      appendClientLog(`[ERROR] reject failed reason=${err.message}`, "error");
      alert(`审核驳回失败: ${err.message}`);
    }
  });

  qs("btn-c-review-save")?.addEventListener("click", async () => {
    try {
      await saveCircuitCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] circuit candidate save failed reason=${err.message}`, "error");
      alert(`回路候选保存失败: ${err.message}`);
    }
  });

  qs("btn-c-review-approve")?.addEventListener("click", async () => {
    try {
      const id = qs("c-review-id")?.value;
      if (!id) {
        alert("请先选择回路候选");
        return;
      }
      const nextId = getNextCircuitCandidateIdAfterCurrent(id);
      await saveCircuitCandidateEditWithoutNavigate();
      await reviewCircuitCandidateOnly("approve");
      await refreshCircuitReviewAfterSaveAndSelect(nextId);
    } catch (err) {
      appendClientLog(`[ERROR] circuit approve failed reason=${err.message}`, "error");
      alert(`回路候选审核通过失败: ${err.message}`);
    }
  });

  qs("btn-c-review-reject")?.addEventListener("click", async () => {
    try {
      const id = qs("c-review-id")?.value;
      if (!id) {
        alert("请先选择回路候选");
        return;
      }
      const nextId = getNextCircuitCandidateIdAfterCurrent(id);
      await saveCircuitCandidateEditWithoutNavigate();
      await reviewCircuitCandidateOnly("reject");
      await refreshCircuitReviewAfterSaveAndSelect(nextId);
    } catch (err) {
      appendClientLog(`[ERROR] circuit reject failed reason=${err.message}`, "error");
      alert(`回路候选驳回失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-save")?.addEventListener("click", async () => {
    try {
      await saveConnectionCandidateEdit();
    } catch (err) {
      appendClientLog(`[ERROR] connection candidate save failed reason=${err.message}`, "error");
      alert(`连接候选保存失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-approve")?.addEventListener("click", async () => {
    try {
      const id = qs("conn-review-id")?.value;
      if (!id) {
        alert("请先选择连接候选");
        return;
      }
      const nextId = getNextConnectionCandidateIdAfterCurrent(id);
      await saveConnectionCandidateEditWithoutNavigate();
      await reviewConnectionCandidateOnly("approve");
      await refreshConnectionReviewAfterSaveAndSelect(nextId);
    } catch (err) {
      appendClientLog(`[ERROR] connection approve failed reason=${err.message}`, "error");
      alert(`连接候选审核通过失败: ${err.message}`);
    }
  });

  qs("btn-conn-review-reject")?.addEventListener("click", async () => {
    try {
      const id = qs("conn-review-id")?.value;
      if (!id) {
        alert("请先选择连接候选");
        return;
      }
      const nextId = getNextConnectionCandidateIdAfterCurrent(id);
      await saveConnectionCandidateEditWithoutNavigate();
      await reviewConnectionCandidateOnly("reject");
      await refreshConnectionReviewAfterSaveAndSelect(nextId);
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
      alert(`入未验证库失败: ${err.message}`);
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
      alert(`未验证条目验证失败: ${err.message}`);
    }
  });

  qs("btn-promote-unverified").addEventListener("click", async () => {
    try {
      await promoteSelectedUnverified();
    } catch (err) {
      appendClientLog(`[ERROR] promote failed reason=${err.message}`, "error");
      alert(`提升到最终库失败: ${err.message}`);
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
      alert(`配置保存失败: ${err.message}`);
    }
  });

  qs("btn-ontology-reload")?.addEventListener("click", async () => {
    try {
      const data = await api("/api/ontology/rules/reload", { method: "POST" });
      syncOntologyStatusHint(data.ontology_rules);
      appendClientLog("[CONFIG] ontology rules reloaded");
    } catch (err) {
      appendClientLog(`[ERROR] ontology reload failed reason=${err.message}`, "error");
      alert(`规则重载失败: ${err.message}`);
    }
  });

  qs("btn-ontology-import")?.addEventListener("click", async () => {
    const input = qs("ontology-rules-file");
    const file = input?.files?.[0];
    if (!file) {
      alert("请先选择 OWL / RDF / Turtle 等本体文件");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    try {
      const resp = await fetch("/api/ontology/rules/import", { method: "POST", body: form });
      const text = await resp.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = { ok: false, error: text };
      }
      if (!resp.ok || data.ok === false) throw new Error(data.error || `HTTP_${resp.status}`);
      syncOntologyStatusHint(data.ontology_rules);
      appendClientLog(
        `[CONFIG] ontology imported -> ${data.output_path || ""} terms=${data.term_map_count ?? ""}`,
      );
      alert(`导入成功\n写入: ${data.output_path}\n术语数: ${data.term_map_count}\n父规则数: ${data.parent_rules_count}`);
      if (input) input.value = "";
      if (state.activeTab === "tab-rules") {
        refreshRulesCenter().catch(() => {});
      }
    } catch (err) {
      appendClientLog(`[ERROR] ontology import failed reason=${err.message}`, "error");
      alert(`导入失败: ${err.message}`);
    }
  });

  document.querySelector("#task-table tbody").addEventListener("click", async (evt) => {
    const row = evt.target.closest("tr[data-task-id]");
    if (!row) return;
    const taskId = row.dataset.taskId;
    const payload = await api(`/api/runs/${taskId}`);
    qs("task-detail").textContent = pretty(payload);
  });

  populateDeepseekPresetSelects();

  const modalDs = qs("modal-deepseek-region");
  if (modalDs) {
    modalDs.addEventListener("click", (evt) => {
      if (evt.target === modalDs) closeDeepseekModal(null);
    });
  }
  const btnDsCancel = qs("btn-ds-cancel");
  if (btnDsCancel) btnDsCancel.addEventListener("click", () => closeDeepseekModal(null));
  const btnDsConfirm = qs("btn-ds-confirm");
  if (btnDsConfirm) {
    btnDsConfirm.addEventListener("click", () => {
      const modal = qs("modal-deepseek-region");
      const kind = modal?.dataset?.kind || "file";
      try {
        const connOv = readDsModalConnectionFields();   // always include full connection params
        const promptOv = buildDeepseekOverrideFromModal(kind);
        const merged = { ...connOv, ...promptOv };
        stashFromDeepseekModal(kind);
        const profileKey = (qs("ds-profile-select")?.value || "").trim();
        closeDeepseekModal({
          profile_key: profileKey,
          deepseek_override: merged,
        });
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  }
  const btnDsLoad = qs("btn-ds-load-profile");
  if (btnDsLoad) {
    btnDsLoad.addEventListener("click", async () => {
      const pk = (qs("ds-profile-select")?.value || "").trim();
      if (!pk) {
        alert("请先在下拉框中选择配置名");
        return;
      }
      try {
        const data = await api("/api/config/deepseek-profiles");
        const profiles = data.profiles || {};
        const p = profiles[pk];
        if (!p) {
          alert("未找到该配置");
          return;
        }
        if (p.enabled != null && qs("ds-deepseek-enabled")) qs("ds-deepseek-enabled").checked = !!p.enabled;
        if (p.api_key != null && p.api_key !== "***" && qs("ds-deepseek-key")) qs("ds-deepseek-key").value = p.api_key;
        if (p.base_url != null && qs("ds-deepseek-base")) qs("ds-deepseek-base").value = p.base_url;
        if (p.model != null && qs("ds-deepseek-model")) qs("ds-deepseek-model").value = p.model;
        if (p.temperature != null && qs("ds-deepseek-temperature")) qs("ds-deepseek-temperature").value = p.temperature;
        if (p.system_prompt != null && qs("ds-system-prompt")) qs("ds-system-prompt").value = p.system_prompt;
        if (p.region_prompt_preset && qs("ds-file-preset-select")) qs("ds-file-preset-select").value = p.region_prompt_preset;
        if (p.region_user_prompt_template != null && qs("ds-file-custom-template")) {
          qs("ds-file-custom-template").value = p.region_user_prompt_template;
          if (p.region_user_prompt_template && qs("ds-file-custom-mode")) {
            qs("ds-file-custom-mode").checked = true;
            const w = qs("ds-file-custom-wrap"); if (w) w.hidden = false;
          }
        }
        if (p.direct_region_prompt_preset && qs("ds-direct-preset-select")) qs("ds-direct-preset-select").value = p.direct_region_prompt_preset;
        if (p.direct_region_user_prompt_template != null && qs("ds-direct-custom-template")) {
          qs("ds-direct-custom-template").value = p.direct_region_user_prompt_template;
          if (p.direct_region_user_prompt_template && qs("ds-direct-custom-mode")) {
            qs("ds-direct-custom-mode").checked = true;
            const w = qs("ds-direct-custom-wrap"); if (w) w.hidden = false;
          }
        }
        updateDsStatusBadge();
        appendClientLog(`[CONFIG] loaded deepseek profile ${pk}`);
      } catch (err) {
        alert(`加载失败: ${err.message}`);
      }
    });
  }
  const btnDsSave = qs("btn-ds-save-profile");
  if (btnDsSave) {
    btnDsSave.addEventListener("click", async () => {
      const name = (qs("ds-save-profile-name")?.value || "").trim();
      if (!name) {
        alert("请填写要保存的配置名");
        return;
      }
      try {
        const profile = {
          ...readDsModalConnectionFields(),
          system_prompt: (qs("ds-system-prompt")?.value || "").trim(),
          region_prompt_preset: qs("ds-file-preset-select")?.value || "default",
          region_user_prompt_template: (qs("ds-file-custom-mode")?.checked ? (qs("ds-file-custom-template")?.value || "").trim() : ""),
          direct_region_prompt_preset: qs("ds-direct-preset-select")?.value || "default",
          direct_region_user_prompt_template: (qs("ds-direct-custom-mode")?.checked ? (qs("ds-direct-custom-template")?.value || "").trim() : ""),
        };
        await api("/api/config/deepseek-profiles", {
          method: "POST",
          body: JSON.stringify({ profile_key: name, profile }),
        });
        stashFromDeepseekModal(qs("modal-deepseek-region")?.dataset?.kind || "file");
        await refreshDeepseekProfileSelect();
        if (qs("ds-profile-select")) qs("ds-profile-select").value = name;
        appendClientLog(`[CONFIG] saved deepseek profile ${name}`);
        alert("配置已保存");
      } catch (err) {
        alert(`保存失败: ${err.message}`);
      }
    });
  }

  const btnDsSync = qs("btn-ds-sync-settings");
  if (btnDsSync) {
    btnDsSync.addEventListener("click", async () => {
      try {
        await refreshStatus();
        fillDeepseekModalFromRuntime();
        updateDsStatusBadge();
        appendClientLog("[CONFIG] DeepSeek 弹窗已从全局设置重新载入");
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  }

  const btnDsSaveGlobal = qs("btn-ds-save-global");
  if (btnDsSaveGlobal) {
    btnDsSaveGlobal.addEventListener("click", async () => {
      try {
        const conn = readDsModalConnectionFields();
        const runtime = state.runtime || {};
        const merged = Object.assign({}, runtime.deepseek || {}, conn);
        await api("/api/config", {
          method: "POST",
          body: JSON.stringify({ deepseek: merged }),
        });
        await refreshStatus();
        appendClientLog("[CONFIG] DeepSeek 参数已写回全局设置");
        alert("全局设置已保存");
      } catch (err) {
        alert(`保存失败: ${err.message}`);
      }
    });
  }

  // Custom template toggle handlers
  const fileCustomToggle = qs("ds-file-custom-mode");
  if (fileCustomToggle) {
    fileCustomToggle.addEventListener("change", () => {
      const wrap = qs("ds-file-custom-wrap");
      if (wrap) wrap.hidden = !fileCustomToggle.checked;
    });
  }
  const directCustomToggle = qs("ds-direct-custom-mode");
  if (directCustomToggle) {
    directCustomToggle.addEventListener("change", () => {
      const wrap = qs("ds-direct-custom-wrap");
      if (wrap) wrap.hidden = !directCustomToggle.checked;
    });
  }

  // Update status badge when connection fields change
  ["ds-deepseek-enabled", "ds-deepseek-key"].forEach((id) => {
    const el = qs(id);
    if (el) el.addEventListener("change", updateDsStatusBadge);
  });
}

async function bootstrap() {
  await refreshStatus();
  await refreshFiles();
  if (state.selectedFileId) {
    await selectFile(state.selectedFileId);
  } else {
    renderFileDetail();
    await refreshReviewDataForActiveTab();
    await refreshUnverified();
    await refreshUnverifiedCircuits();
    await refreshUnverifiedConnections();
  }
  await refreshTasks();
  await refreshLogs();
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

