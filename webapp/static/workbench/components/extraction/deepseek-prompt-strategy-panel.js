export function renderDeepSeekPromptStrategyPanel(host, { config, t, onFieldChange }) {
  if (!host) return;

  host.innerHTML = `
    <div class="deepseek-panel-shell">
      <h5>${t("extraction.deepseek.promptTitle")}</h5>
      <div class="deepseek-toggle-grid three-col">
        <label><input id="ds-use-ontology" type="checkbox" ${config.useOntologyContext ? "checked" : ""} /> ${t("extraction.deepseek.useOntologyContext")}</label>
        <label><input id="ds-use-mapping" type="checkbox" ${config.useTableMappingContext ? "checked" : ""} /> ${t("extraction.deepseek.useTableMappingContext")}</label>
        <label><input id="ds-file-meta" type="checkbox" ${config.includeFileMetadata ? "checked" : ""} /> ${t("extraction.deepseek.includeFileMetadata")}</label>
      </div>
      <div class="deepseek-field-grid single-col prompt-grid">
        <div class="field-block">
          <label>${t("extraction.deepseek.systemPrompt")}</label>
          <textarea id="ds-system-prompt" rows="4">${config.systemPrompt || ""}</textarea>
        </div>
        <div class="field-block">
          <label>${t("extraction.deepseek.extractPrompt")}</label>
          <textarea id="ds-extraction-prompt" rows="8">${config.extractionPromptTemplate || ""}</textarea>
        </div>
      </div>
    </div>
  `;

  host.querySelector("#ds-use-ontology")?.addEventListener("change", (event) => onFieldChange?.("useOntologyContext", Boolean(event.target.checked)));
  host.querySelector("#ds-use-mapping")?.addEventListener("change", (event) => onFieldChange?.("useTableMappingContext", Boolean(event.target.checked)));
  host.querySelector("#ds-file-meta")?.addEventListener("change", (event) => onFieldChange?.("includeFileMetadata", Boolean(event.target.checked)));
  host.querySelector("#ds-system-prompt")?.addEventListener("change", (event) => onFieldChange?.("systemPrompt", event.target.value));
  host.querySelector("#ds-extraction-prompt")?.addEventListener("change", (event) => onFieldChange?.("extractionPromptTemplate", event.target.value));
}
