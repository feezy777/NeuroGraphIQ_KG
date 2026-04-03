export function renderExtractionWorkbenchLayout(host, { deepseekEnabled = false } = {}) {
  if (!host) {
    return {
      layout: deepseekEnabled ? "workbench-horizontal" : "standard-horizontal",
      ratios: deepseekEnabled ? { left: 0.2, center: 0.6, right: 0.2 } : { left: 0.22, center: 0.56, right: 0.22 },
    };
  }

  const layout = deepseekEnabled ? "workbench-horizontal" : "standard-horizontal";
  const ratios = deepseekEnabled ? { left: 0.2, center: 0.6, right: 0.2 } : { left: 0.22, center: 0.56, right: 0.22 };

  host.setAttribute("data-layout-mode", deepseekEnabled ? "deepseek" : "standard");
  host.classList.toggle("deepseek-layout", deepseekEnabled);

  return { layout, ratios };
}
