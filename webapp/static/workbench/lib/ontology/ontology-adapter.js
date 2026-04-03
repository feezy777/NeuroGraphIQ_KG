import { parseOntologyPlaceholder } from "./ontology-placeholder-parser.js";

function previewTextFromPayload(preview) {
  if (!preview) return "";
  if (preview.mode === "text") return String(preview.text || "");
  if (preview.mode === "json") return JSON.stringify(preview.value || {}, null, 2);
  if (preview.mode === "table") {
    const rows = preview.rows || [];
    return rows.slice(0, 120).map((row) => JSON.stringify(row)).join("\n");
  }
  return "";
}

async function readOntologyRawText(fileRecord, fileService) {
  const contentUrl = fileService.getContentUrl(fileRecord.file_id);
  try {
    const response = await fetch(contentUrl, { cache: "no-store" });
    if (response.ok) {
      const text = await response.text();
      if (String(text || "").trim()) return text;
    }
  } catch {
    // fallthrough to paged preview fallback
  }

  const chunks = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages && page <= 50) {
    const preview = await fileService.getPreview(fileRecord.file_id, {
      page,
      pageSize: 2000,
      view: "text",
    });
    if (preview.mode !== "text") return previewTextFromPayload(preview);
    chunks.push(String(preview.text || ""));
    totalPages = Number(preview.total_pages || 1);
    page += 1;
  }

  return chunks.join("\n");
}

export async function importOntologyWithAdapter(fileRecord, fileService) {
  const parseStart = `[ONTOLOGY][PARSE] start file=${fileRecord.filename}`;
  const text = await readOntologyRawText(fileRecord, fileService);
  const preview = await fileService.getPreview(fileRecord.file_id, {
    page: 1,
    pageSize: 400,
    view: "text",
  });
  const parsed = parseOntologyPlaceholder({
    filename: fileRecord.filename,
    fileType: fileRecord.file_type,
    text,
  });

  const parseFinish =
    `[ONTOLOGY][PARSE] finish file=${fileRecord.filename}` +
    ` classes=${parsed.stats.classes}` +
    ` object_properties=${parsed.stats.objectProperties}` +
    ` data_properties=${parsed.stats.dataProperties}` +
    ` individuals=${parsed.stats.individuals}`;

  return {
    file: fileRecord,
    preview,
    parsed,
    logs: [
      parseStart,
      parseFinish,
      `[ONTOLOGY] import_success file=${fileRecord.filename} classes=${parsed.stats.classes} relations=${parsed.stats.objectProperties} mode=${parsed.meta.parseMode}`,
    ],
  };
}

