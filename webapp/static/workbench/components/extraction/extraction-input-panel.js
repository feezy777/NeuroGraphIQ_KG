export function renderExtractionInputPanel(host, { ontologyCount = 0, fileCount = 0, selectedFileCount = 0 } = {}) {
  if (!host) return;
  host.classList.add("extraction-top-left");
  host.setAttribute("data-panel-role", "input_resources");
  host.setAttribute("data-ontology-count", String(ontologyCount));
  host.setAttribute("data-file-count", String(fileCount));
  host.setAttribute("data-file-selected", String(selectedFileCount));
}
