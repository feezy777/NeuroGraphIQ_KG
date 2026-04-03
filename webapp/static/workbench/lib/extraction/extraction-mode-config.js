export const EXTRACTION_RUNTIME_MODES = {
  PLACEHOLDER: "placeholder",
  DEEPSEEK: "deepseek",
};

export const EXTRACTION_JOB_MODES = [
  { id: "placeholder_fast", label: "placeholder_fast" },
  { id: "placeholder_balanced", label: "placeholder_balanced" },
];

export const EXTRACTION_OUTPUT_OPTIONS = [
  { id: "triples", label: "triples" },
  { id: "entities", label: "entities" },
  { id: "relations", label: "relations" },
  { id: "candidates", label: "candidates" },
];

export function resolveRuntimeMode(deepseekEnabled) {
  return deepseekEnabled ? EXTRACTION_RUNTIME_MODES.DEEPSEEK : EXTRACTION_RUNTIME_MODES.PLACEHOLDER;
}
