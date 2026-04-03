const BUILTIN_MODELS = ["deepseek-chat", "deepseek-reasoner", "custom"];

function safeText(value, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

export function renderDeepSeekSettings(container, { deepseek, t, onSave }) {
  if (!container) return;

  const currentModel = safeText(deepseek?.model, "deepseek-chat");
  const useCustomModel = !BUILTIN_MODELS.includes(currentModel) || currentModel === "custom";
  const selectModel = useCustomModel ? "custom" : currentModel;
  const customModelValue = useCustomModel ? currentModel : "";
  const hasApiKey = Boolean(deepseek?.hasApiKey);

  container.innerHTML = `
    <div class="settings-block">
      <h4>${t("settings.deepseekConfig")}</h4>
      <div class="form-grid compact">
        <label for="settings-deepseek-enabled">${t("settings.deepseekEnabled")}</label>
        <label class="inline-row settings-inline-switch">
          <input id="settings-deepseek-enabled" type="checkbox" ${deepseek?.enabled ? "checked" : ""} />
          <span>${deepseek?.enabled ? t("common.yes") : t("common.no")}</span>
        </label>

        <label for="settings-deepseek-base-url">${t("settings.deepseekBaseUrl")}</label>
        <input id="settings-deepseek-base-url" type="text" value="${safeText(deepseek?.baseUrl, "https://api.deepseek.com")}" />

        <label for="settings-deepseek-model">${t("settings.deepseekModel")}</label>
        <select id="settings-deepseek-model">
          <option value="deepseek-chat" ${selectModel === "deepseek-chat" ? "selected" : ""}>deepseek-chat</option>
          <option value="deepseek-reasoner" ${selectModel === "deepseek-reasoner" ? "selected" : ""}>deepseek-reasoner</option>
          <option value="custom" ${selectModel === "custom" ? "selected" : ""}>custom</option>
        </select>

        <label for="settings-deepseek-custom-model">${t("settings.deepseekCustomModel")}</label>
        <input id="settings-deepseek-custom-model" type="text" value="${customModelValue}" ${selectModel === "custom" ? "" : "disabled"} />

        <label for="settings-deepseek-api-key">${t("settings.deepseekApiKey")}</label>
        <div class="deepseek-secret-field">
          <input id="settings-deepseek-api-key" type="password" value="" placeholder="${hasApiKey ? t("settings.deepseekKeyConfigured") : ""}" />
          <button id="settings-deepseek-toggle-key" class="ide-btn" type="button">${t("extraction.deepseek.showHide")}</button>
        </div>
      </div>
      <div class="meta-text settings-tip-line">${t("settings.deepseekKeyKeepHint")}</div>
      <div class="inline-row settings-action-row">
        <button id="settings-deepseek-save" class="ide-btn ide-btn-primary" type="button">${t("settings.deepseekSave")}</button>
        <span id="settings-deepseek-status" class="meta-text"></span>
      </div>
    </div>
  `;

  const enabledNode = container.querySelector("#settings-deepseek-enabled");
  const modelNode = container.querySelector("#settings-deepseek-model");
  const customModelNode = container.querySelector("#settings-deepseek-custom-model");
  const baseUrlNode = container.querySelector("#settings-deepseek-base-url");
  const apiKeyNode = container.querySelector("#settings-deepseek-api-key");
  const toggleKeyNode = container.querySelector("#settings-deepseek-toggle-key");
  const saveNode = container.querySelector("#settings-deepseek-save");
  const statusNode = container.querySelector("#settings-deepseek-status");

  modelNode?.addEventListener("change", () => {
    const isCustom = modelNode.value === "custom";
    customModelNode.disabled = !isCustom;
    if (isCustom) customModelNode.focus();
  });

  toggleKeyNode?.addEventListener("click", () => {
    if (!apiKeyNode) return;
    apiKeyNode.type = apiKeyNode.type === "password" ? "text" : "password";
  });

  saveNode?.addEventListener("click", async () => {
    if (!statusNode || !enabledNode || !baseUrlNode || !modelNode || !customModelNode || !apiKeyNode) return;
    statusNode.textContent = t("settings.saving");
    saveNode.disabled = true;
    try {
      let model = safeText(modelNode.value, "deepseek-chat");
      if (model === "custom") {
        model = safeText(customModelNode.value);
        if (!model) {
          statusNode.textContent = t("settings.deepseekCustomRequired");
          saveNode.disabled = false;
          return;
        }
      }

      await onSave?.({
        enabled: Boolean(enabledNode.checked),
        baseUrl: safeText(baseUrlNode.value, "https://api.deepseek.com"),
        model,
        apiKey: safeText(apiKeyNode.value),
      });
      statusNode.textContent = t("settings.deepseekSaveSuccess");
      apiKeyNode.value = "";
      apiKeyNode.placeholder = t("settings.deepseekKeyConfigured");
    } catch (error) {
      statusNode.textContent = `${t("settings.deepseekSaveFailed")}: ${String(error?.message || error)}`;
    } finally {
      saveNode.disabled = false;
    }
  });
}
