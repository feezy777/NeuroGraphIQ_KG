/**
 * @typedef {"region" | "circuit" | "connection"} ExtractionTargetType
 */

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

/**
 * @typedef {"text" | "json" | "structured_json"} ResponseFormatOption
 */

/**
 * @typedef {"placeholder" | "deepseek"} ExtractionRuntimeMode
 */

/**
 * @typedef {"deepseek-chat" | "deepseek-reasoner" | "custom"} ModelOption
 */

/**
 * @typedef {Object} DeepSeekConfig
 * @property {boolean} enabled
 * @property {string} provider
 * @property {string} baseUrl
 * @property {string} apiKey
 * @property {string} projectTag
 * @property {number} timeoutSec
 * @property {number} retryCount
 * @property {ModelOption} model
 * @property {string} customModelName
 * @property {number} temperature
 * @property {number} topP
 * @property {number} maxTokens
 * @property {boolean} stream
 * @property {ResponseFormatOption} responseFormat
 * @property {string} systemPrompt
 * @property {string} extractionPromptTemplate
 * @property {boolean} useOntologyContext
 * @property {boolean} useTableMappingContext
 * @property {boolean} includeFileMetadata
 * @property {boolean} strictSchemaMode
 * @property {boolean} enableEvidenceMode
 * @property {boolean} fallbackToPlaceholder
 * @property {boolean} dryRun
 */

/**
 * @typedef {Object} DeepSeekJobSummary
 * @property {boolean} enabled
 * @property {string} provider
 * @property {string} model
 * @property {number} temperature
 * @property {number} topP
 * @property {number} maxTokens
 * @property {number} timeoutSec
 * @property {number} retryCount
 * @property {boolean} stream
 * @property {ResponseFormatOption} responseFormat
 * @property {boolean} useOntologyContext
 * @property {boolean} useTableMappingContext
 * @property {boolean} includeFileMetadata
 * @property {boolean} strictSchemaMode
 * @property {boolean} enableEvidenceMode
 * @property {boolean} fallbackToPlaceholder
 * @property {boolean} dryRun
 * @property {string} projectTag
 */

/**
 * @typedef {Object} ExtractionScopeConfig
 * @property {GranularityLevel} granularity
 * @property {GranularityTableMapping} tableMapping
 */

/**
 * @typedef {Object} ExtractionJob
 * @property {string} id
 * @property {string} status
 * @property {string} mode
 * @property {ExtractionRuntimeMode} runtimeMode
 * @property {string} output
 * @property {string[]} targets
 * @property {string[]} fileIds
 * @property {string} ontologyId
 * @property {string} createdAt
 * @property {string} [startedAt]
 * @property {string} [finishedAt]
 * @property {GranularityLevel} granularity
 * @property {GranularityTableMapping} tableMapping
 * @property {DeepSeekJobSummary} deepseek
 */

/**
 * @typedef {Object} ExtractionResultSummary
 * @property {number} entities
 * @property {number} relations
 * @property {number} circuits
 */

export {};
