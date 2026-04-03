export function renderDeepSeekConnectionPanel(host, { config, t, onFieldChange }) {
  if (!host) return;

  host.innerHTML = `
    <div class="deepseek-panel-shell">
      <h5>${t("extraction.deepseek.baseTitle")}</h5>
      <div class="deepseek-field-grid two-col">
        <div class="field-block span-2">
          <div class="deepseek-toggle-grid two-col">
            <label><input id="ds-use-task-override" type="checkbox" ${config.useTaskOverride ? "checked" : ""} /> ${t("extraction.deepseek.useTaskOverride")}</label>
          </div>
          <div class="meta-text">${t("extraction.deepseek.useTaskOverrideHint")}</div>
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.provider")}</label>
          <input type="text" value="${config.provider || "deepseek"}" readonly />
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.baseUrl")}</label>
          <input id="ds-base-url" type="text" value="${config.baseUrl || ""}" />
        </div>
        <div class="field-block span-2">
          <label>${t("extraction.deepseek.apiKey")}</label>
          <div class="deepseek-secret-field">
            <input id="ds-api-key" type="password" value="${config.apiKey || ""}" autocomplete="off" />
            <button type="button" id="ds-api-key-toggle" class="ide-btn">${t("extraction.deepseek.showHide")}</button>
          </div>
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.projectTag")}</label>
          <input id="ds-project-tag" type="text" value="${config.projectTag || ""}" />
        </div>
        <div class="field-block inline-pair-block">
          <label>${t("extraction.deepseek.timeoutSec")} / ${t("extraction.deepseek.retryCount")}</label>
          <div class="inline-pair">
            <input id="ds-timeout" type="number" min="1" step="1" value="${config.timeoutSec}" />
            <input id="ds-retry" type="number" min="0" step="1" value="${config.retryCount}" />
          </div>
        </div>
      </div>
    </div>
  `;

  const keyNode = host.querySelector("#ds-api-key");
  host.querySelector("#ds-api-key-toggle")?.addEventListener("click", () => {
    if (!keyNode) return;
    keyNode.type = keyNode.type === "password" ? "text" : "password";
  });

  host.querySelector("#ds-base-url")?.addEventListener("change", (event) => onFieldChange?.("baseUrl", event.target.value));
  host.querySelector("#ds-use-task-override")?.addEventListener("change", (event) => onFieldChange?.("useTaskOverride", Boolean(event.target.checked)));
  host.querySelector("#ds-api-key")?.addEventListener("change", (event) => onFieldChange?.("apiKey", event.target.value));
  host.querySelector("#ds-project-tag")?.addEventListener("change", (event) => onFieldChange?.("projectTag", event.target.value));
  host.querySelector("#ds-timeout")?.addEventListener("change", (event) => onFieldChange?.("timeoutSec", Number(event.target.value)));
  host.querySelector("#ds-retry")?.addEventListener("change", (event) => onFieldChange?.("retryCount", Number(event.target.value)));
}
