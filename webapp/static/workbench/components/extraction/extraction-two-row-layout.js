export function renderExtractionTwoRowLayout(host, { deepseekEnabled = false } = {}) {
  const info = {
    layout: "top-two-bottom-one",
    ratios: {
      top: deepseekEnabled ? 0.34 : 0.35,
      bottom: deepseekEnabled ? 0.66 : 0.65,
      topLeft: 0.5,
      topRight: 0.5,
    },
    areas: {
      topLeft: "input_resources",
      topRight: "task_and_summary",
      bottom: "deepseek_full_width",
    },
  };

  if (!host) {
    return info;
  }

  host.setAttribute("data-layout-mode", info.layout);
  host.classList.toggle("deepseek-layout", Boolean(deepseekEnabled));
  host.classList.add("extraction-two-row-grid");

  return info;
}
