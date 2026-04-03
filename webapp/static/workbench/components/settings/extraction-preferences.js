import { GRANULARITY_OPTIONS, getGranularityOption } from "../../lib/extraction/granularity-config.js";

export function renderExtractionPreferences(container, {
  language,
  defaultGranularity,
  defaultOutput,
  workspacePreferences,
  t,
  onGranularityChange,
  onOutputChange,
  onWorkspacePrefChange,
}) {
  if (!container) return;

  const granularityOptions = GRANULARITY_OPTIONS.map((item) => {
    const label = language === "en-US" ? item.labelEn : item.labelZh;
    return `<option value="${item.id}" ${item.id === defaultGranularity ? "selected" : ""}>${label}</option>`;
  }).join("");

  const outputOptions = ["triples", "entities", "relations", "candidates"]
    .map((opt) => `<option value="${opt}" ${opt === defaultOutput ? "selected" : ""}>${opt}</option>`)
    .join("");

  const mapping = getGranularityOption(defaultGranularity).tableMapping;

  container.innerHTML = `
    <div class="settings-block">
      <h4>${t("settings.extractionPrefs")}</h4>
      <div class="form-grid compact">
        <label for="settings-default-granularity">${t("settings.defaultGranularity")}</label>
        <select id="settings-default-granularity">${granularityOptions}</select>
        <label for="settings-default-output">${t("settings.defaultOutput")}</label>
        <select id="settings-default-output">${outputOptions}</select>
      </div>
      <div class="mapping-grid extraction-block">
        <div class="kv-key">${t("settings.mappingPreview")}</div>
        <div class="kv-value">-</div>
        <div class="kv-key">${t("settings.mappingEntity")}</div>
        <div class="kv-value mono">${mapping.entityTable}</div>
        <div class="kv-key">${t("settings.mappingRelation")}</div>
        <div class="kv-value mono">${mapping.relationTable}</div>
        <div class="kv-key">${t("settings.mappingCircuit")}</div>
        <div class="kv-value mono">${mapping.circuitTable}</div>
      </div>
    </div>

    <div class="settings-block">
      <h4>${t("settings.workspacePrefs")}</h4>
      <div class="form-grid compact">
        <label for="settings-default-tab">${t("settings.defaultTab")}</label>
        <select id="settings-default-tab">
          <option value="tab-overview" ${workspacePreferences.defaultMainTab === "tab-overview" ? "selected" : ""}>tab-overview</option>
          <option value="tab-files" ${workspacePreferences.defaultMainTab === "tab-files" ? "selected" : ""}>tab-files</option>
          <option value="tab-extraction" ${workspacePreferences.defaultMainTab === "tab-extraction" ? "selected" : ""}>tab-extraction</option>
        </select>
      </div>
      <div class="checkbox-row settings-checkbox-row">
        <label><input id="settings-auto-scroll" type="checkbox" ${workspacePreferences.autoScrollLogs ? "checked" : ""} /> ${t("settings.autoScrollLogs")}</label>
        <label><input id="settings-remember-collapse" type="checkbox" ${workspacePreferences.rememberPanelCollapse ? "checked" : ""} /> ${t("settings.rememberPanelCollapse")}</label>
      </div>
    </div>
  `;

  container.querySelector("#settings-default-granularity")?.addEventListener("change", (event) => {
    onGranularityChange?.(event.target.value);
  });
  container.querySelector("#settings-default-output")?.addEventListener("change", (event) => {
    onOutputChange?.(event.target.value);
  });
  container.querySelector("#settings-default-tab")?.addEventListener("change", (event) => {
    onWorkspacePrefChange?.("defaultMainTab", event.target.value);
  });
  container.querySelector("#settings-auto-scroll")?.addEventListener("change", (event) => {
    onWorkspacePrefChange?.("autoScrollLogs", Boolean(event.target.checked));
  });
  container.querySelector("#settings-remember-collapse")?.addEventListener("change", (event) => {
    onWorkspacePrefChange?.("rememberPanelCollapse", Boolean(event.target.checked));
  });
}
