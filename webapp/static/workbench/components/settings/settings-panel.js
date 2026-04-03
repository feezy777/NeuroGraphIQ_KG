import { renderLanguageSwitcher } from "./language-switcher.js";
import { renderAppearancePanel } from "./appearance-panel.js";
import { renderExtractionPreferences } from "./extraction-preferences.js";

export function renderSettingsPanel(host, params) {
  if (!host) return;
  host.innerHTML = `
    <div class="settings-layout">
      <section id="settings-language-host"></section>
      <section id="settings-appearance-host"></section>
      <section id="settings-extraction-host"></section>
    </div>
  `;

  renderLanguageSwitcher(host.querySelector("#settings-language-host"), params);
  renderAppearancePanel(host.querySelector("#settings-appearance-host"), params);
  renderExtractionPreferences(host.querySelector("#settings-extraction-host"), params);
}
