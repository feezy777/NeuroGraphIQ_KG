const DEFAULT_SYSTEM_PROMPT = [
  "You are a neuroscience KG extraction assistant.",
  "Follow ontology constraints and output deterministic structured data.",
].join("\n");

const DEFAULT_EXTRACTION_TEMPLATE = [
  "Extract candidate entities/relations/circuits from provided inputs.",
  "Respect selected granularity and table mapping.",
  "Return concise JSON result for downstream validation.",
].join("\n");

export function createDefaultDeepSeekConfig() {
  return {
    enabled: false,
    useTaskOverride: false,
    provider: "deepseek",
    baseUrl: "https://api.deepseek.com",
    apiKey: "",
    projectTag: "",
    timeoutSec: 120,
    retryCount: 2,
    model: "deepseek-chat",
    customModelName: "",
    temperature: 0.2,
    topP: 0.95,
    maxTokens: 4096,
    stream: false,
    responseFormat: "json",
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    extractionPromptTemplate: DEFAULT_EXTRACTION_TEMPLATE,
    useOntologyContext: true,
    useTableMappingContext: true,
    includeFileMetadata: true,
    strictSchemaMode: true,
    enableEvidenceMode: false,
    fallbackToPlaceholder: true,
    dryRun: false,
  };
}

function toBool(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === "1" || value === 1 || value === "true") return true;
  if (value === "0" || value === 0 || value === "false") return false;
  return fallback;
}

function toNumber(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function sanitizeDeepSeekConfig(input) {
  const base = createDefaultDeepSeekConfig();
  const raw = input && typeof input === "object" ? input : {};
  const model = ["deepseek-chat", "deepseek-reasoner", "custom"].includes(raw.model) ? raw.model : base.model;
  return {
    ...base,
    ...raw,
    enabled: toBool(raw.enabled, base.enabled),
    useTaskOverride: toBool(raw.useTaskOverride, base.useTaskOverride),
    provider: String(raw.provider || base.provider),
    baseUrl: String(raw.baseUrl || base.baseUrl),
    apiKey: String(raw.apiKey || ""),
    projectTag: String(raw.projectTag || ""),
    timeoutSec: Math.max(1, Math.floor(toNumber(raw.timeoutSec, base.timeoutSec))),
    retryCount: Math.max(0, Math.floor(toNumber(raw.retryCount, base.retryCount))),
    model,
    customModelName: String(raw.customModelName || ""),
    temperature: Math.max(0, Math.min(2, toNumber(raw.temperature, base.temperature))),
    topP: Math.max(0, Math.min(1, toNumber(raw.topP, base.topP))),
    maxTokens: Math.max(1, Math.floor(toNumber(raw.maxTokens, base.maxTokens))),
    stream: toBool(raw.stream, base.stream),
    responseFormat: ["text", "json", "structured_json"].includes(raw.responseFormat) ? raw.responseFormat : base.responseFormat,
    systemPrompt: String(raw.systemPrompt || base.systemPrompt),
    extractionPromptTemplate: String(raw.extractionPromptTemplate || base.extractionPromptTemplate),
    useOntologyContext: toBool(raw.useOntologyContext, base.useOntologyContext),
    useTableMappingContext: toBool(raw.useTableMappingContext, base.useTableMappingContext),
    includeFileMetadata: toBool(raw.includeFileMetadata, base.includeFileMetadata),
    strictSchemaMode: toBool(raw.strictSchemaMode, base.strictSchemaMode),
    enableEvidenceMode: toBool(raw.enableEvidenceMode, base.enableEvidenceMode),
    fallbackToPlaceholder: toBool(raw.fallbackToPlaceholder, base.fallbackToPlaceholder),
    dryRun: toBool(raw.dryRun, base.dryRun),
  };
}

export function resolveDeepSeekModel(config) {
  const safe = sanitizeDeepSeekConfig(config);
  if (safe.model !== "custom") return safe.model;
  return safe.customModelName.trim() || "custom";
}

export function toDeepSeekJobSummary(config) {
  const safe = sanitizeDeepSeekConfig(config);
  return {
    enabled: safe.enabled,
    useTaskOverride: safe.useTaskOverride,
    provider: safe.provider,
    model: resolveDeepSeekModel(safe),
    temperature: safe.temperature,
    topP: safe.topP,
    maxTokens: safe.maxTokens,
    timeoutSec: safe.timeoutSec,
    retryCount: safe.retryCount,
    stream: safe.stream,
    responseFormat: safe.responseFormat,
    useOntologyContext: safe.useOntologyContext,
    useTableMappingContext: safe.useTableMappingContext,
    includeFileMetadata: safe.includeFileMetadata,
    strictSchemaMode: safe.strictSchemaMode,
    enableEvidenceMode: safe.enableEvidenceMode,
    fallbackToPlaceholder: safe.fallbackToPlaceholder,
    dryRun: safe.dryRun,
    projectTag: safe.projectTag,
  };
}

export function maskSensitiveField(field, value) {
  if (field === "apiKey") {
    return value ? "***" : "";
  }
  const text = String(value ?? "");
  if (text.length > 120) {
    return `${text.slice(0, 117)}...`;
  }
  return text;
}
