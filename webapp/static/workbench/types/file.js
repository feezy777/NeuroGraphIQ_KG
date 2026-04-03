/**
 * @typedef {Object} SourceFile
 * @property {string} file_id
 * @property {string} filename
 * @property {string} file_type
 * @property {string} uploaded_at
 * @property {string} [status]
 * @property {string} [overall_label]
 * @property {number} [score]
 * @property {boolean} [blocked_on_load]
 */

/**
 * @typedef {"uploaded" | "validating" | "validated" | "validation_failed" | "processed" | "removed"} FileParseStatus
 */

export {};
