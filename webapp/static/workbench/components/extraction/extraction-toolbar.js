import { GRANULARITY_OPTIONS } from "../../lib/extraction/granularity-config.js";
import { EXTRACTION_JOB_MODES, EXTRACTION_OUTPUT_OPTIONS } from "../../lib/extraction/extraction-mode-config.js";

function granularityText(option, language) {
  if (!option) return "-";
  return language === "en-US" ? option.labelEn : option.labelZh;
}

export function renderExtractionToolbar(host, {
  t,
  language,
  mode,
  output,
  granularity,
  deepseekEnabled,
  deepseekSummary,
  onModeChange,
  onOutputChange,
  onGranularityChange,
  onDeepSeekToggle,
  onStart,
}) {
  if (!host) return;

  const modeOptions = EXTRACTION_JOB_MODES.map((item) => `<option value="${item.id}" ${item.id === mode ? "selected" : ""}>${item.label}</option>`).join("");
  const outputOptions = EXTRACTION_OUTPUT_OPTIONS.map((item) => `<option value="${item.id}" ${item.id === output ? "selected" : ""}>${item.label}</option>`).join("");

  const granularityButtons = GRANULARITY_OPTIONS.map((item) => {
    const active = item.id === granularity;
    return `<button type="button" class="granularity-seg-btn ${active ? "active" : ""}" data-granularity-value="${item.id}">${granularityText(item, language)}</button>`;
  }).join("");

  const modelSummary = deepseekEnabled
    ? `model=${deepseekSummary?.model || "-"} | temp=${deepseekSummary?.temperature ?? "-"} | format=${deepseekSummary?.responseFormat || "-"}`
    : "-";

  host.innerHTML = `
    <div class="extraction-toolbar-shell">
      <div class="extraction-toolbar-grid">
        <div class="toolbar-field">
          <label>${t("extraction.mode")}</label>
          <select id="extract-mode-select-inline">${modeOptions}</select>
        </div>
        <div class="toolbar-field">
          <label>${t("extraction.granularity.title")}</label>
          <div class="granularity-seg-group">${granularityButtons}</div>
        </div>
        <div class="toolbar-field">
          <label>${t("extraction.output")}</label>
          <select id="extract-output-select-inline">${outputOptions}</select>
        </div>
        <div class="toolbar-field toolbar-switch-field">
          <label for="extract-deepseek-enabled-inline">${t("extraction.deepseek.enableLabel")}</label>
          <input id="extract-deepseek-enabled-inline" type="checkbox" ${deepseekEnabled ? "checked" : ""} />
        </div>
        <div class="toolbar-field toolbar-summary-field">
          <label>${t("extraction.toolbar.modelSummary")}</label>
          <div class="toolbar-summary-text">${modelSummary}</div>
        </div>
        <div class="toolbar-field toolbar-action-field">
          <button id="btn-start-extraction-inline" class="ide-btn ide-btn-primary">${t("extraction.start")}</button>
        </div>
      </div>
    </div>
  `;

  host.querySelector("#extract-mode-select-inline")?.addEventListener("change", (event) => {
    onModeChange?.(String(event.target.value || "placeholder_balanced"));
  });
  host.querySelector("#extract-output-select-inline")?.addEventListener("change", (event) => {
    onOutputChange?.(String(event.target.value || "triples"));
  });
  host.querySelector("#extract-deepseek-enabled-inline")?.addEventListener("change", (event) => {
    onDeepSeekToggle?.(Boolean(event.target.checked));
  });
  host.querySelector("#btn-start-extraction-inline")?.addEventListener("click", () => {
    onStart?.();
  });
  host.querySelectorAll("button[data-granularity-value]").forEach((node) => {
    node.addEventListener("click", () => {
      const next = String(node.getAttribute("data-granularity-value") || "coarse");
      onGranularityChange?.(next);
    });
  });
}
