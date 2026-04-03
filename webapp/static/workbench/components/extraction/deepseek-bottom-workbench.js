import { renderDeepSeekWorkbench } from "./deepseek-workbench.js";

export function renderDeepSeekBottomWorkbench(host, { enabled, config, t, onFieldChange }) {
  if (!host) return;
  host.setAttribute("data-panel-role", "deepseek_full_width");
  host.setAttribute("data-enabled", enabled ? "1" : "0");
  renderDeepSeekWorkbench(host, { enabled, config, t, onFieldChange });
}
