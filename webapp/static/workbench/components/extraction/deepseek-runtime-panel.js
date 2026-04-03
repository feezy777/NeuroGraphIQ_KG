export function renderDeepSeekRuntimePanel(host, { config, t, onFieldChange }) {
  if (!host) return;

  host.innerHTML = `
    <div class="deepseek-panel-shell">
      <h5>${t("extraction.deepseek.runtimeTitle")}</h5>
      <div class="deepseek-toggle-grid two-col">
        <label><input id="ds-strict-schema" type="checkbox" ${config.strictSchemaMode ? "checked" : ""} /> ${t("extraction.deepseek.strictSchemaMode")}</label>
        <label><input id="ds-evidence" type="checkbox" ${config.enableEvidenceMode ? "checked" : ""} /> ${t("extraction.deepseek.enableEvidenceMode")}</label>
        <label><input id="ds-fallback" type="checkbox" ${config.fallbackToPlaceholder ? "checked" : ""} /> ${t("extraction.deepseek.fallbackToPlaceholder")}</label>
        <label><input id="ds-dry-run" type="checkbox" ${config.dryRun ? "checked" : ""} /> ${t("extraction.deepseek.dryRun")}</label>
      </div>
    </div>
  `;

  host.querySelector("#ds-strict-schema")?.addEventListener("change", (event) => onFieldChange?.("strictSchemaMode", Boolean(event.target.checked)));
  host.querySelector("#ds-evidence")?.addEventListener("change", (event) => onFieldChange?.("enableEvidenceMode", Boolean(event.target.checked)));
  host.querySelector("#ds-fallback")?.addEventListener("change", (event) => onFieldChange?.("fallbackToPlaceholder", Boolean(event.target.checked)));
  host.querySelector("#ds-dry-run")?.addEventListener("change", (event) => onFieldChange?.("dryRun", Boolean(event.target.checked)));
}
