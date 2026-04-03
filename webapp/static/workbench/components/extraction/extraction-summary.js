export function renderExtractionSummary(host, {
  t,
  ontologyLabel,
  selectedFiles,
  targets,
  granularityLabel,
  mapping,
  runtimeMode = "placeholder",
  deepseek = null,
}) {
  if (!host) return;

  const fileLabel = selectedFiles.length ? selectedFiles.join(", ") : "-";
  const targetLabel = targets.length ? targets.join(", ") : "-";
  const entityTable = mapping?.entityTable || "-";
  const relationTable = mapping?.relationTable || "-";
  const circuitTable = mapping?.circuitTable || "-";
  const modelLabel = runtimeMode === "deepseek" ? deepseek?.model || "-" : "-";
  const temperatureLabel = runtimeMode === "deepseek" ? deepseek?.temperature ?? "-" : "-";
  const responseFormatLabel = runtimeMode === "deepseek" ? deepseek?.responseFormat || "-" : "-";
  const modeLabel = runtimeMode === "deepseek" ? t("extraction.deepseek.modeDeepseek") : t("extraction.deepseek.modePlaceholder");

  host.innerHTML = `
    <div class="settings-block extraction-block">
      <h4>${t("extraction.granularity.summaryTitle")}</h4>
      <div class="mapping-grid">
        <div class="kv-key">${t("extraction.granularity.ontology")}</div>
        <div class="kv-value">${ontologyLabel || "-"}</div>
        <div class="kv-key">${t("extraction.granularity.files")}</div>
        <div class="kv-value">${fileLabel}</div>
        <div class="kv-key">${t("extraction.granularity.targets")}</div>
        <div class="kv-value">${targetLabel}</div>
        <div class="kv-key">${t("extraction.granularity.selected")}</div>
        <div class="kv-value">${granularityLabel}</div>
        <div class="kv-key">${t("extraction.summary.mode")}</div>
        <div class="kv-value">${modeLabel}</div>
        <div class="kv-key">${t("extraction.summary.model")}</div>
        <div class="kv-value mono">${modelLabel}</div>
        <div class="kv-key">${t("extraction.summary.temperature")}</div>
        <div class="kv-value">${temperatureLabel}</div>
        <div class="kv-key">${t("extraction.summary.responseFormat")}</div>
        <div class="kv-value mono">${responseFormatLabel}</div>
        <div class="kv-key">${t("extraction.granularity.entityTable")}</div>
        <div class="kv-value mono">${entityTable}</div>
        <div class="kv-key">${t("extraction.granularity.relationTable")}</div>
        <div class="kv-value mono">${relationTable}</div>
        <div class="kv-key">${t("extraction.granularity.circuitTable")}</div>
        <div class="kv-value mono">${circuitTable}</div>
      </div>
    </div>
  `;
}
