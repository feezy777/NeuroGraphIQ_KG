export function renderExtractionTaskSummaryPanel(host, { deepseekEnabled = false, activeJobId = "" } = {}) {
  if (!host) return;
  host.classList.add("extraction-top-right");
  host.setAttribute("data-panel-role", "task_and_summary");
  host.setAttribute("data-deepseek-enabled", deepseekEnabled ? "1" : "0");
  host.setAttribute("data-active-job-id", activeJobId || "");
}
