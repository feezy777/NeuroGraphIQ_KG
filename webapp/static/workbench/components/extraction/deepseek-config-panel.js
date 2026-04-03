import { renderDeepSeekModelSelector } from "./deepseek-model-selector.js";
import { renderDeepSeekPromptPanel } from "./deepseek-prompt-panel.js";
import { renderExtractionRuntimeOptions } from "./extraction-runtime-options.js";

export function renderDeepSeekConfigPanel(host, { enabled, config, t, onFieldChange }) {
  if (!host) return;
  if (!enabled) {
    host.innerHTML = "";
    return;
  }

  host.innerHTML = `
    <div class="settings-block extraction-block">
      <h4>${t("extraction.deepseek.configTitle")}</h4>
      <div class="deepseek-section">
        <h5>${t("extraction.deepseek.baseTitle")}</h5>
        <div class="form-grid compact">
          <label for="deepseek-provider">${t("extraction.deepseek.provider")}</label>
          <input id="deepseek-provider" type="text" value="${config.provider}" readonly />
          <label for="deepseek-base-url">${t("extraction.deepseek.baseUrl")}</label>
          <input id="deepseek-base-url" type="text" value="${config.baseUrl}" />
          <label for="deepseek-api-key">${t("extraction.deepseek.apiKey")}</label>
          <div class="deepseek-secret-field">
            <input id="deepseek-api-key" type="password" value="${config.apiKey || ""}" autocomplete="off" />
            <button type="button" id="deepseek-api-key-toggle" class="ide-btn">${t("extraction.deepseek.showHide")}</button>
          </div>
          <label for="deepseek-project-tag">${t("extraction.deepseek.projectTag")}</label>
          <input id="deepseek-project-tag" type="text" value="${config.projectTag || ""}" />
        </div>
      </div>
      <section id="deepseek-model-selector-host"></section>
      <section id="deepseek-prompt-panel-host"></section>
      <section id="deepseek-runtime-options-host"></section>
    </div>
  `;

  const apiKeyNode = host.querySelector("#deepseek-api-key");
  const toggleBtn = host.querySelector("#deepseek-api-key-toggle");
  toggleBtn?.addEventListener("click", () => {
    if (!apiKeyNode) return;
    apiKeyNode.type = apiKeyNode.type === "password" ? "text" : "password";
  });

  host.querySelector("#deepseek-base-url")?.addEventListener("change", (event) => {
    onFieldChange?.("baseUrl", event.target.value);
  });
  host.querySelector("#deepseek-api-key")?.addEventListener("change", (event) => {
    onFieldChange?.("apiKey", event.target.value);
  });
  host.querySelector("#deepseek-project-tag")?.addEventListener("change", (event) => {
    onFieldChange?.("projectTag", event.target.value);
  });

  renderDeepSeekModelSelector(host.querySelector("#deepseek-model-selector-host"), { config, t, onFieldChange });
  renderDeepSeekPromptPanel(host.querySelector("#deepseek-prompt-panel-host"), { config, t, onFieldChange });
  renderExtractionRuntimeOptions(host.querySelector("#deepseek-runtime-options-host"), { config, t, onFieldChange });
}
