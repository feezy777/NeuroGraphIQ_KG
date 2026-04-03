import { GRANULARITY_OPTIONS } from "../../lib/extraction/granularity-config.js";

export function renderGranularitySelector(host, { language, selectedGranularity, t, onChange }) {
  if (!host) return;

  const optionsHtml = GRANULARITY_OPTIONS.map((option) => {
    const label = language === "en-US" ? option.labelEn : option.labelZh;
    const desc = language === "en-US" ? option.descriptionEn : option.descriptionZh;
    const active = option.id === selectedGranularity;
    return `
      <label class="granularity-item ${active ? "selected" : ""}">
        <input type="radio" name="granularity_selector" value="${option.id}" ${active ? "checked" : ""} />
        <span class="granularity-label">${label}</span>
        <span class="granularity-desc">${desc}</span>
      </label>
    `;
  }).join("");

  host.innerHTML = `
    <div class="settings-block extraction-block">
      <h4>${t("extraction.granularity.title")}</h4>
      <div class="meta-text">${t("extraction.granularity.subtitle")}</div>
      <div class="granularity-options">${optionsHtml}</div>
    </div>
  `;

  host.querySelectorAll("input[name='granularity_selector']").forEach((node) => {
    node.addEventListener("change", () => {
      if (node.checked) onChange?.(node.value);
    });
  });
}
