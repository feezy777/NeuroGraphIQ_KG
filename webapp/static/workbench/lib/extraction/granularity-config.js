/**
 * @typedef {"coarse" | "mid" | "fine"} GranularityLevel
 */

/**
 * @typedef {Object} GranularityTableMapping
 * @property {string} entityTable
 * @property {string} relationTable
 * @property {string} circuitTable
 */

/**
 * @typedef {Object} GranularityOption
 * @property {GranularityLevel} id
 * @property {string} labelZh
 * @property {string} labelEn
 * @property {string} descriptionZh
 * @property {string} descriptionEn
 * @property {GranularityTableMapping} tableMapping
 */

export const GRANULARITY_OPTIONS = [
  {
    id: "coarse",
    labelZh: "粗颗粒度（主脑区）",
    labelEn: "Coarse (Major Region)",
    descriptionZh: "面向主脑区层级，适合全局结构和框架建模。",
    descriptionEn: "Major-region level for global structure and framework modeling.",
    tableMapping: {
      entityTable: "brain_region_coarse",
      relationTable: "brain_connection_coarse",
      circuitTable: "brain_circuit_coarse",
    },
  },
  {
    id: "mid",
    labelZh: "中颗粒度（亚脑区）",
    labelEn: "Intermediate (Sub Region)",
    descriptionZh: "面向亚脑区层级，平衡覆盖率与细节。",
    descriptionEn: "Sub-region level balancing coverage and detail.",
    tableMapping: {
      entityTable: "brain_region_mid",
      relationTable: "brain_connection_mid",
      circuitTable: "brain_circuit_mid",
    },
  },
  {
    id: "fine",
    labelZh: "细颗粒度（Allen 细分脑区）",
    labelEn: "Fine (Allen Region)",
    descriptionZh: "面向 Allen 细分层级，适合高精度结构表达。",
    descriptionEn: "Allen-level fine granularity for high-precision structures.",
    tableMapping: {
      entityTable: "brain_region_fine",
      relationTable: "brain_connection_fine",
      circuitTable: "brain_circuit_fine",
    },
  },
];

export function getGranularityOption(id) {
  return GRANULARITY_OPTIONS.find((item) => item.id === id) || GRANULARITY_OPTIONS[0];
}

export function getGranularityTableMapping(id) {
  return getGranularityOption(id).tableMapping;
}
