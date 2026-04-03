export function renderTableMappingPanel(host, { mapping, t }) {
  if (!host) return;
  const entityTable = mapping?.entityTable || "-";
  const relationTable = mapping?.relationTable || "-";
  const circuitTable = mapping?.circuitTable || "-";

  host.innerHTML = `
    <div class="settings-block extraction-block">
      <h4>${t("extraction.granularity.mappingTitle")}</h4>
      <div class="mapping-grid">
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
