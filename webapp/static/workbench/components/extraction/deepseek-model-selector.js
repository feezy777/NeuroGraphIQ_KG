export function renderDeepSeekModelSelector(host, { config, t, onFieldChange }) {
  if (!host) return;
  const showCustom = config.model === "custom";
  host.innerHTML = `
    <div class="deepseek-section">
      <h5>${t("extraction.deepseek.modelTitle")}</h5>
      <div class="form-grid compact">
        <label for="deepseek-model">${t("extraction.deepseek.model")}</label>
        <select id="deepseek-model">
          <option value="deepseek-chat" ${config.model === "deepseek-chat" ? "selected" : ""}>deepseek-chat</option>
          <option value="deepseek-reasoner" ${config.model === "deepseek-reasoner" ? "selected" : ""}>deepseek-reasoner</option>
          <option value="custom" ${config.model === "custom" ? "selected" : ""}>custom</option>
        </select>
        <label for="deepseek-custom-model">${t("extraction.deepseek.customModel")}</label>
        <input id="deepseek-custom-model" type="text" value="${config.customModelName || ""}" ${showCustom ? "" : "disabled"} />
        <label for="deepseek-temperature">${t("extraction.deepseek.temperature")}</label>
        <input id="deepseek-temperature" type="number" min="0" max="2" step="0.05" value="${config.temperature}" />
        <label for="deepseek-top-p">${t("extraction.deepseek.topP")}</label>
        <input id="deepseek-top-p" type="number" min="0" max="1" step="0.01" value="${config.topP}" />
        <label for="deepseek-max-tokens">${t("extraction.deepseek.maxTokens")}</label>
        <input id="deepseek-max-tokens" type="number" min="1" step="1" value="${config.maxTokens}" />
        <label for="deepseek-response-format">${t("extraction.deepseek.responseFormat")}</label>
        <select id="deepseek-response-format">
          <option value="text" ${config.responseFormat === "text" ? "selected" : ""}>text</option>
          <option value="json" ${config.responseFormat === "json" ? "selected" : ""}>json</option>
          <option value="structured_json" ${config.responseFormat === "structured_json" ? "selected" : ""}>structured_json</option>
        </select>
      </div>
      <div class="checkbox-row settings-checkbox-row">
        <label><input id="deepseek-stream" type="checkbox" ${config.stream ? "checked" : ""} /> ${t("extraction.deepseek.stream")}</label>
      </div>
    </div>
  `;

  host.querySelector("#deepseek-model")?.addEventListener("change", (event) => {
    onFieldChange?.("model", event.target.value);
  });
  host.querySelector("#deepseek-custom-model")?.addEventListener("change", (event) => {
    onFieldChange?.("customModelName", event.target.value);
  });
  host.querySelector("#deepseek-temperature")?.addEventListener("change", (event) => {
    onFieldChange?.("temperature", Number(event.target.value));
  });
  host.querySelector("#deepseek-top-p")?.addEventListener("change", (event) => {
    onFieldChange?.("topP", Number(event.target.value));
  });
  host.querySelector("#deepseek-max-tokens")?.addEventListener("change", (event) => {
    onFieldChange?.("maxTokens", Number(event.target.value));
  });
  host.querySelector("#deepseek-response-format")?.addEventListener("change", (event) => {
    onFieldChange?.("responseFormat", event.target.value);
  });
  host.querySelector("#deepseek-stream")?.addEventListener("change", (event) => {
    onFieldChange?.("stream", Boolean(event.target.checked));
  });
}
