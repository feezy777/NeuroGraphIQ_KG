export function renderDeepSeekToggle(host, { enabled, t, onToggle }) {
  if (!host) return;
  host.innerHTML = `
    <div class="settings-block extraction-block">
      <div class="deepseek-toggle-row">
        <label for="extract-deepseek-enabled" class="deepseek-toggle-label">${t("extraction.deepseek.enableLabel")}</label>
        <input id="extract-deepseek-enabled" type="checkbox" ${enabled ? "checked" : ""} />
      </div>
      <div class="meta-text">${t("extraction.deepseek.enableHint")}</div>
    </div>
  `;

  host.querySelector("#extract-deepseek-enabled")?.addEventListener("change", (event) => {
    onToggle?.(Boolean(event.target.checked));
  });
}
