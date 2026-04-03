export function renderAppearancePanel(container, { appearance, t, onApplyLight }) {
  if (!container) return;
  container.innerHTML = `
    <div class="settings-block">
      <h4>${t("settings.appearance")}</h4>
      <div class="appearance-options">
        <label class="appearance-item ${appearance === "light-workspace" ? "selected" : ""}">
          <input type="radio" name="appearance_mode" value="light-workspace" ${appearance === "light-workspace" ? "checked" : ""} />
          <span>${t("settings.lightWorkspace")}</span>
        </label>
        <label class="appearance-item disabled">
          <input type="radio" name="appearance_mode" value="dark-workspace" disabled />
          <span>${t("settings.darkWorkspaceDisabled")}</span>
        </label>
      </div>
    </div>
  `;

  const lightNode = container.querySelector("input[value='light-workspace']");
  lightNode?.addEventListener("change", () => {
    if (lightNode.checked) onApplyLight?.();
  });
}
