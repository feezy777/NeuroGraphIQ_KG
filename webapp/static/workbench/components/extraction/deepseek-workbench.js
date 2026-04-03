import { renderDeepSeekConnectionPanel } from "./deepseek-connection-panel.js";
import { renderDeepSeekModelPanel } from "./deepseek-model-panel.js";
import { renderDeepSeekPromptStrategyPanel } from "./deepseek-prompt-strategy-panel.js";
import { renderDeepSeekRuntimePanel } from "./deepseek-runtime-panel.js";

export function renderDeepSeekWorkbench(host, { enabled, config, t, onFieldChange }) {
  if (!host) return;

  if (!enabled) {
    host.innerHTML = `
      <div class="deepseek-workbench-disabled">
        <div class="meta-text">${t("extraction.deepseek.workbenchDisabled")}</div>
      </div>
    `;
    return;
  }

  host.innerHTML = `
    <div class="deepseek-workbench-shell">
      <div class="deepseek-workbench-head">
        <h4>${t("extraction.deepseek.workbenchTitle")}</h4>
        <div class="meta-text">${t("extraction.deepseek.workbenchHint")}</div>
      </div>
      <div class="deepseek-workbench-grid">
        <section class="deepseek-workbench-panel ds-connection" id="deepseek-connection-panel-host"></section>
        <section class="deepseek-workbench-panel ds-model" id="deepseek-model-panel-host"></section>
        <section class="deepseek-workbench-panel ds-prompt" id="deepseek-prompt-panel-host"></section>
        <section class="deepseek-workbench-panel ds-runtime" id="deepseek-runtime-panel-host"></section>
      </div>
    </div>
  `;

  renderDeepSeekConnectionPanel(host.querySelector("#deepseek-connection-panel-host"), { config, t, onFieldChange });
  renderDeepSeekModelPanel(host.querySelector("#deepseek-model-panel-host"), { config, t, onFieldChange });
  renderDeepSeekPromptStrategyPanel(host.querySelector("#deepseek-prompt-panel-host"), { config, t, onFieldChange });
  renderDeepSeekRuntimePanel(host.querySelector("#deepseek-runtime-panel-host"), { config, t, onFieldChange });
}
