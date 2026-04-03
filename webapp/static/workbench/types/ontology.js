/**
 * @typedef {Object} OntologyFile
 * @property {string} file_id
 * @property {string} filename
 * @property {string} file_type
 * @property {string} uploaded_at
 * @property {string} [original_path]
 */

/**
 * @typedef {Object} OntologyEntity
 * @property {string} id
 * @property {string} type
 * @property {string} label
 * @property {string} iri
 * @property {string} [parent]
 * @property {string} [description]
 */

/**
 * @typedef {Object} OntologyWorkspaceState
 * @property {OntologyFile[]} files
 * @property {string} activeOntologyId
 * @property {Object.<string, any>} parsedByFileId
 * @property {string[]} loadLogs
 */

export {};
