export function renderLanguageSwitcher(container, { language, t, onChange }) {
  if (!container) return;
  container.innerHTML = `
    <div class="settings-block">
      <h4>${t("settings.language")}</h4>
      <div class="inline-row">
        <label class="inline-label" for="settings-language-select">${t("settings.language")}</label>
        <select id="settings-language-select" class="settings-select">
          <option value="zh-CN" ${language === "zh-CN" ? "selected" : ""}>${t("settings.optionChinese")}</option>
          <option value="en-US" ${language === "en-US" ? "selected" : ""}>${t("settings.optionEnglish")}</option>
        </select>
      </div>
    </div>
  `;

  const node = container.querySelector("#settings-language-select");
  node?.addEventListener("change", () => {
    onChange?.(node.value || "zh-CN");
  });
}
