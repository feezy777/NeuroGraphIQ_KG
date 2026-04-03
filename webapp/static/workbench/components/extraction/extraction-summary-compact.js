export function renderExtractionSummaryCompact(host, {
  t,
  ontologyLabel,
  selectedFiles,
  targets,
  granularityLabel,
  mapping,
  runtimeMode = "placeholder",
  deepseek = null,
  resultSummary = null,
}) {
  if (!host) return;

  const fileCount = selectedFiles.length;
  const targetLabel = targets.length ? targets.join(", ") : "-";
  const modeLabel = runtimeMode === "deepseek" ? t("extraction.deepseek.modeDeepseek") : t("extraction.deepseek.modePlaceholder");
  const entityCount = resultSummary?.entities ?? "-";
  const relationCount = resultSummary?.relations ?? "-";
  const circuitCount = resultSummary?.circuits ?? "-";

  host.innerHTML = `
    <div class="summary-compact-grid">
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.mode")}</div>
        <div class="summary-value">${modeLabel}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.granularity.selected")}</div>
        <div class="summary-value">${granularityLabel}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.model")}</div>
        <div class="summary-value mono">${runtimeMode === "deepseek" ? deepseek?.model || "-" : "-"}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.temperature")}</div>
        <div class="summary-value">${runtimeMode === "deepseek" ? deepseek?.temperature ?? "-" : "-"}</div>
      </div>
      <div class="summary-compact-card span-2">
        <div class="summary-title">${t("extraction.granularity.ontology")}</div>
        <div class="summary-value mono">${ontologyLabel || "-"}</div>
      </div>
      <div class="summary-compact-card span-2">
        <div class="summary-title">${t("extraction.granularity.targets")}</div>
        <div class="summary-value">${targetLabel}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.granularity.files")}</div>
        <div class="summary-value">${fileCount}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.responseFormat")}</div>
        <div class="summary-value mono">${runtimeMode === "deepseek" ? deepseek?.responseFormat || "-" : "-"}</div>
      </div>
      <div class="summary-compact-card span-2">
        <div class="summary-title">${t("extraction.granularity.entityTable")}</div>
        <div class="summary-value mono">${mapping?.entityTable || "-"}</div>
      </div>
      <div class="summary-compact-card span-2">
        <div class="summary-title">${t("extraction.granularity.relationTable")}</div>
        <div class="summary-value mono">${mapping?.relationTable || "-"}</div>
      </div>
      <div class="summary-compact-card span-2">
        <div class="summary-title">${t("extraction.granularity.circuitTable")}</div>
        <div class="summary-value mono">${mapping?.circuitTable || "-"}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.entityCount")}</div>
        <div class="summary-value">${entityCount}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.relationCount")}</div>
        <div class="summary-value">${relationCount}</div>
      </div>
      <div class="summary-compact-card">
        <div class="summary-title">${t("extraction.summary.circuitCount")}</div>
        <div class="summary-value">${circuitCount}</div>
      </div>
    </div>
  `;
}
