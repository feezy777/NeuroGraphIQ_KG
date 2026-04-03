export function renderDeepSeekPromptPanel(host, { config, t, onFieldChange }) {
  if (!host) return;
  host.innerHTML = `
    <div class="deepseek-section">
      <h5>${t("extraction.deepseek.promptTitle")}</h5>
      <div class="form-grid compact">
        <label for="deepseek-system-prompt">${t("extraction.deepseek.systemPrompt")}</label>
        <textarea id="deepseek-system-prompt" rows="3">${config.systemPrompt || ""}</textarea>
        <label for="deepseek-extract-prompt">${t("extraction.deepseek.extractPrompt")}</label>
        <textarea id="deepseek-extract-prompt" rows="5">${config.extractionPromptTemplate || ""}</textarea>
      </div>
      <div class="checkbox-row settings-checkbox-row">
        <label><input id="deepseek-use-ontology" type="checkbox" ${config.useOntologyContext ? "checked" : ""} /> ${t("extraction.deepseek.useOntologyContext")}</label>
        <label><input id="deepseek-use-mapping" type="checkbox" ${config.useTableMappingContext ? "checked" : ""} /> ${t("extraction.deepseek.useTableMappingContext")}</label>
        <label><input id="deepseek-include-file-meta" type="checkbox" ${config.includeFileMetadata ? "checked" : ""} /> ${t("extraction.deepseek.includeFileMetadata")}</label>
      </div>
    </div>
  `;

  host.querySelector("#deepseek-system-prompt")?.addEventListener("change", (event) => {
    onFieldChange?.("systemPrompt", event.target.value);
  });
  host.querySelector("#deepseek-extract-prompt")?.addEventListener("change", (event) => {
    onFieldChange?.("extractionPromptTemplate", event.target.value);
  });
  host.querySelector("#deepseek-use-ontology")?.addEventListener("change", (event) => {
    onFieldChange?.("useOntologyContext", Boolean(event.target.checked));
  });
  host.querySelector("#deepseek-use-mapping")?.addEventListener("change", (event) => {
    onFieldChange?.("useTableMappingContext", Boolean(event.target.checked));
  });
  host.querySelector("#deepseek-include-file-meta")?.addEventListener("change", (event) => {
    onFieldChange?.("includeFileMetadata", Boolean(event.target.checked));
  });
}
