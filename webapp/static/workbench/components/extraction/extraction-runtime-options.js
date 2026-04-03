export function renderExtractionRuntimeOptions(host, { config, t, onFieldChange }) {
  if (!host) return;
  host.innerHTML = `
    <div class="deepseek-section">
      <h5>${t("extraction.deepseek.runtimeTitle")}</h5>
      <div class="form-grid compact">
        <label for="deepseek-timeout">${t("extraction.deepseek.timeoutSec")}</label>
        <input id="deepseek-timeout" type="number" min="1" step="1" value="${config.timeoutSec}" />
        <label for="deepseek-retry">${t("extraction.deepseek.retryCount")}</label>
        <input id="deepseek-retry" type="number" min="0" step="1" value="${config.retryCount}" />
      </div>
      <div class="checkbox-row settings-checkbox-row">
        <label><input id="deepseek-strict-schema" type="checkbox" ${config.strictSchemaMode ? "checked" : ""} /> ${t("extraction.deepseek.strictSchemaMode")}</label>
        <label><input id="deepseek-evidence-mode" type="checkbox" ${config.enableEvidenceMode ? "checked" : ""} /> ${t("extraction.deepseek.enableEvidenceMode")}</label>
        <label><input id="deepseek-fallback" type="checkbox" ${config.fallbackToPlaceholder ? "checked" : ""} /> ${t("extraction.deepseek.fallbackToPlaceholder")}</label>
        <label><input id="deepseek-dry-run" type="checkbox" ${config.dryRun ? "checked" : ""} /> ${t("extraction.deepseek.dryRun")}</label>
      </div>
    </div>
  `;

  host.querySelector("#deepseek-timeout")?.addEventListener("change", (event) => {
    onFieldChange?.("timeoutSec", Number(event.target.value));
  });
  host.querySelector("#deepseek-retry")?.addEventListener("change", (event) => {
    onFieldChange?.("retryCount", Number(event.target.value));
  });
  host.querySelector("#deepseek-strict-schema")?.addEventListener("change", (event) => {
    onFieldChange?.("strictSchemaMode", Boolean(event.target.checked));
  });
  host.querySelector("#deepseek-evidence-mode")?.addEventListener("change", (event) => {
    onFieldChange?.("enableEvidenceMode", Boolean(event.target.checked));
  });
  host.querySelector("#deepseek-fallback")?.addEventListener("change", (event) => {
    onFieldChange?.("fallbackToPlaceholder", Boolean(event.target.checked));
  });
  host.querySelector("#deepseek-dry-run")?.addEventListener("change", (event) => {
    onFieldChange?.("dryRun", Boolean(event.target.checked));
  });
}
