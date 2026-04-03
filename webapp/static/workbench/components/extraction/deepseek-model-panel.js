export function renderDeepSeekModelPanel(host, { config, t, onFieldChange }) {
  if (!host) return;
  const showCustom = config.model === "custom";

  host.innerHTML = `
    <div class="deepseek-panel-shell">
      <h5>${t("extraction.deepseek.modelTitle")}</h5>
      <div class="deepseek-field-grid two-col">
        <div class="field-block">
          <label>${t("extraction.deepseek.model")}</label>
          <select id="ds-model">
            <option value="deepseek-chat" ${config.model === "deepseek-chat" ? "selected" : ""}>deepseek-chat</option>
            <option value="deepseek-reasoner" ${config.model === "deepseek-reasoner" ? "selected" : ""}>deepseek-reasoner</option>
            <option value="custom" ${config.model === "custom" ? "selected" : ""}>custom</option>
          </select>
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.customModel")}</label>
          <input id="ds-custom-model" type="text" value="${config.customModelName || ""}" ${showCustom ? "" : "disabled"} />
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.temperature")}</label>
          <input id="ds-temperature" type="number" min="0" max="2" step="0.05" value="${config.temperature}" />
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.topP")}</label>
          <input id="ds-top-p" type="number" min="0" max="1" step="0.01" value="${config.topP}" />
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.maxTokens")}</label>
          <input id="ds-max-tokens" type="number" min="1" step="1" value="${config.maxTokens}" />
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.responseFormat")}</label>
          <select id="ds-response-format">
            <option value="text" ${config.responseFormat === "text" ? "selected" : ""}>text</option>
            <option value="json" ${config.responseFormat === "json" ? "selected" : ""}>json</option>
            <option value="structured_json" ${config.responseFormat === "structured_json" ? "selected" : ""}>structured_json</option>
          </select>
        </div>
      </div>
      <div class="deepseek-toggle-grid">
        <label><input id="ds-stream" type="checkbox" ${config.stream ? "checked" : ""} /> ${t("extraction.deepseek.stream")}</label>
      </div>
    </div>
  `;

  host.querySelector("#ds-model")?.addEventListener("change", (event) => onFieldChange?.("model", event.target.value));
  host.querySelector("#ds-custom-model")?.addEventListener("change", (event) => onFieldChange?.("customModelName", event.target.value));
  host.querySelector("#ds-temperature")?.addEventListener("change", (event) => onFieldChange?.("temperature", Number(event.target.value)));
  host.querySelector("#ds-top-p")?.addEventListener("change", (event) => onFieldChange?.("topP", Number(event.target.value)));
  host.querySelector("#ds-max-tokens")?.addEventListener("change", (event) => onFieldChange?.("maxTokens", Number(event.target.value)));
  host.querySelector("#ds-response-format")?.addEventListener("change", (event) => onFieldChange?.("responseFormat", event.target.value));
  host.querySelector("#ds-stream")?.addEventListener("change", (event) => onFieldChange?.("stream", Boolean(event.target.checked)));
}
