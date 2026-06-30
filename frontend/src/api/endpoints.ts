import { ApiError, buildApiUrl, deleteJson, getJson, patchJson, postJson, uploadForm } from './client'
import {
  filterNonEmptyIds,
  normalizeOptionalString,
  normalizeOptionalUuid,
  omitUndefined,
} from './payloadUtils'

// ── Common ────────────────────────────────────────────────────────────────────
export interface Paginated<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

// ── Health ────────────────────────────────────────────────────────────────────
export interface HealthDatabaseInfo {
  name: string
  connected: boolean
  schema_status: string
  host: string
  port: number
}

export interface HealthResponse {
  status: string
  version: string
  database?: HealthDatabaseInfo
  modules: Record<string, string>
}
export const fetchHealth = () => getJson<HealthResponse>('/api/health')

// ── Database Admin ────────────────────────────────────────────────────────────
export type DatabaseSchemaStatus =
  | 'mvp1_ready'
  | 'legacy'
  | 'partial'
  | 'empty'
  | 'unreachable'

export interface DatabaseConnectionInfo {
  host: string
  port: number
  user: string
  current_database: string
  connected: boolean
  schema_status: DatabaseSchemaStatus
  missing_tables: string[]
  notes: string[]
}

export interface DatabaseListItem {
  name: string
  schema_status: DatabaseSchemaStatus
  is_current: boolean
  missing_tables: string[]
  notes: string[]
}

export interface DatabaseListResponse {
  host: string
  port: number
  current_database: string
  items: DatabaseListItem[]
}

export interface DatabaseValidationResponse {
  database: string
  schema_status: DatabaseSchemaStatus
  missing_tables: string[]
  present_tables: string[]
  notes: string[]
}

export interface DatabaseSwitchResponse {
  ok: boolean
  previous_database: string
  current_database: string
  schema_status: DatabaseSchemaStatus
  message: string
}

export const getDatabaseStatus = () => getJson<DatabaseConnectionInfo>('/api/database/status')
export const listDatabases = () => getJson<DatabaseListResponse>('/api/database/databases')
export const validateDatabase = (database: string) =>
  getJson<DatabaseValidationResponse>('/api/database/validate', { database })
export const switchDatabase = (database: string) =>
  postJson<DatabaseSwitchResponse>('/api/database/switch', { database })

// ── Resources ─────────────────────────────────────────────────────────────────
export interface AtlasResource {
  id: string
  resource_code: string
  source_atlas: string
  source_version: string
  resource_type: string
  species: string
  granularity_level: string
  granularity_family: string
  template_space: string
  cn_name: string | null
  en_name: string | null
  description: string | null
  remark: string | null
  status: string
  created_at: string
  updated_at: string
  deleted_at?: string | null
}

export interface ResourceQuery {
  [key: string]: string | number | undefined
  status?: string
  source_atlas?: string
  granularity_level?: string
  granularity_family?: string
  limit?: number
  offset?: number
}

/** UI may use status=all; backend only accepts active | inactive | archived. */
export function cleanResourceParams(params?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!params) return undefined
  const clean = { ...params }
  if (clean.status === 'all' || clean.status === '') {
    delete clean.status
  }
  return clean
}

export function sanitizeResourceQuery(params?: ResourceQuery): ResourceQuery | undefined {
  return cleanResourceParams(params) as ResourceQuery | undefined
}

export const listResources = (p?: ResourceQuery) =>
  getJson<Paginated<AtlasResource>>('/api/resources', sanitizeResourceQuery(p))
export const fetchResources = listResources

export interface ResourceOptions {
  resource_type: string[]
  species: string[]
  granularity_level: string[]
  granularity_family: string[]
  template_space: string[]
  status: string[]
}

export const getResource = (resourceId: string, includeArchived = false) =>
  getJson<AtlasResource>(`/api/resources/${resourceId}`, includeArchived ? { include_archived: true } : undefined)
export const getResourceOptions = () =>
  getJson<ResourceOptions>('/api/resources/options')
export const fetchResourceOptions = getResourceOptions

// ── Resource Files ────────────────────────────────────────────────────────────
export interface ResourceFile {
  id: string
  resource_id: string
  file_code: string | null
  original_filename: string
  stored_filename: string
  storage_path: string
  file_ext: string
  mime_type: string | null
  file_type: string
  file_role: string
  sha256: string
  file_size: number
  status: string
  description: string | null
  remark: string | null
  created_at: string
  updated_at: string
  deleted_at?: string | null
  source_workspace_file_id?: string | null
  intermediate_status?: 'ready' | 'missing' | 'failed' | 'archived' | 'unknown' | null
  latest_intermediate_artifact_id?: string | null
  latest_normalization_run_id?: string | null
  latest_intermediate_kind?: string | null
  latest_intermediate_row_count?: number | null
  latest_intermediate_error?: string | null
}

export interface FileQuery {
  [key: string]: string | number | undefined
  status?: string
  file_type?: string
  file_role?: string
  limit?: number
  offset?: number
}

export interface FileOptions {
  file_type: string[]
  file_role: string[]
  status: string[]
  preview_supported_types: string[]
}

export interface ResourceFileUpdate {
  file_type?: string
  file_role?: string
  description?: string | null
  remark?: string | null
  status?: string
}

export type PreviewKind = 'text' | 'json' | 'xml' | 'csv' | 'image' | 'binary' | 'unsupported' | 'missing' | 'error'

export interface FilePreview {
  file_id: string
  filename: string
  file_type: string
  mime_type: string | null
  preview_kind: PreviewKind
  is_truncated: boolean
  max_bytes: number
  size_bytes: number
  encoding: string | null
  content: string | null
  metadata: Record<string, unknown>
  error_message: string | null
}

export const listResourceFiles = (resourceId: string, p?: FileQuery) =>
  getJson<Paginated<ResourceFile>>(`/api/resources/${resourceId}/files`, p)
export const fetchResourceFiles = listResourceFiles
export const getFileOptions = () => getJson<FileOptions>('/api/files/options')
export const fetchFilesOptions = getFileOptions
export const getFile = (fileId: string, includeArchived = false) =>
  getJson<ResourceFile>(
    `/api/files/${fileId}`,
    includeArchived ? { include_archived: true } : undefined,
  )
export const updateFile = (fileId: string, body: ResourceFileUpdate) =>
  patchJson<ResourceFile>(`/api/files/${fileId}`, body)
export const deleteFile = (fileId: string) =>
  deleteJson<ResourceFile>(`/api/files/${fileId}`)

export interface FileDeleteRequest {
  confirmation_text: string
  operator: string
  reason: string
  delete_physical_file?: boolean
}

export interface FileDeleteResult {
  file_id: string
  resource_id: string
  status: string
  deleted_counts: Record<string, number>
  can_reupload_same_sha256: boolean
  physical_file_deleted?: boolean
  physical_file_error?: string | null
}

export const restoreFile = (fileId: string) =>
  postJson<ResourceFile>(`/api/files/${fileId}/restore`)

export const destructiveDeleteFile = (fileId: string, body: FileDeleteRequest) =>
  postJson<FileDeleteResult>(`/api/files/${fileId}/destructive-delete`, body)
export const getFilePreview = (fileId: string) =>
  getJson<FilePreview>(`/api/files/${fileId}/preview`)
export const getFileDownloadUrl = (fileId: string) =>
  buildApiUrl(`/api/files/${fileId}/download`)

// ── Import Batches ────────────────────────────────────────────────────────────
export type ParserKey = 'aal3_xml' | 'aal3_label_table' | 'macro96_xlsx' | string

export type ImportBatchStatus =
  | 'created'
  | 'queued'
  | 'running'
  | 'parsed'
  | 'candidate_generated'
  | 'validated'
  | 'reviewed'
  | 'promoted'
  | 'failed'
  | 'cancelled'
  | 'archived'
  | string

export function isMacro96Batch(batch: { parser_key?: string | null } | null | undefined): boolean {
  return batch?.parser_key === 'macro96_xlsx'
}

export function isAal3Batch(batch: { parser_key?: string | null } | null | undefined): boolean {
  const k = batch?.parser_key
  return k === 'aal3_xml' || k === 'aal3_label_table'
}

export interface ImportBatch {
  id: string
  batch_code: string
  resource_id: string
  batch_type: string
  parser_key: ParserKey | null
  status: ImportBatchStatus
  description: string | null
  remark: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
  failed_at?: string | null
  cancelled_at?: string | null
  error_message?: string | null
}

/** Cancelled batches are soft-deleted and hidden from workbench list UIs. */
export const WORKBENCH_HIDDEN_BATCH_STATUSES = new Set(['cancelled'])

export const WORKBENCH_BATCH_STATUS_FILTER_OPTIONS = [
  'created',
  'queued',
  'running',
  'parsed',
  'candidate_generated',
  'validation_dispatched',
  'completed',
  'failed',
] as const

export function filterWorkbenchBatches(items: ImportBatch[]): ImportBatch[] {
  return items.filter(b => !WORKBENCH_HIDDEN_BATCH_STATUSES.has(b.status))
}

export interface ImportBatchFileEnriched {
  id: string
  batch_id: string
  file_id: string
  resource_id: string
  file_role_in_batch: string
  sort_order: number
  created_at: string
  original_filename: string | null
  file_type: string | null
  file_role: string | null
  file_status: string | null
  sha256: string | null
  file_size: number | null
  intermediate_status: string | null
  latest_intermediate_artifact_id: string | null
  is_active: boolean
  can_parse: boolean
  inactive_reason: string | null
  warning: string | null
}

export interface ImportBatchDetail extends ImportBatch {
  files: ImportBatchFileEnriched[]
  recent_events: ImportBatchEvent[]
  warnings: string[]
  next_allowed_actions: string[]
}

export const fetchImportBatches = (p?: {
  status?: string
  resource_id?: string
  parser_key?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<ImportBatch>>('/api/import-batches', p)
export const fetchImportBatchOptions = () => getJson<Record<string, string[]>>('/api/import-batches/options')
export const getImportBatch = (batchId: string) =>
  getJson<ImportBatchDetail>(`/api/import-batches/${batchId}`)
export const getImportBatchFiles = (batchId: string) =>
  getJson<{ items: ImportBatchFileEnriched[]; total: number; warnings: string[] }>(
    `/api/import-batches/${batchId}/files`,
  )
export const getImportBatchEvents = (batchId: string, p?: { limit?: number; offset?: number }) =>
  getJson<Paginated<ImportBatchEvent>>(`/api/import-batches/${batchId}/events`, p)

// ── Raw AAL3 Labels ───────────────────────────────────────────────────────────
export interface RawAal3Label {
  id: string
  parse_run_id: string
  batch_id: string
  resource_id: string
  label_index: number | null
  label_value: number | null
  raw_name: string
  en_name: string | null
  cn_name: string | null
  laterality: string
  region_base_name: string | null
  source_label_id: string | null
  created_at: string
}
export const fetchRawAal3Labels = (p?: {
  batch_id?: string
  parse_run_id?: string
  resource_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<RawAal3Label>>('/api/raw-parsing/aal3-labels', p)
export const fetchRawParsingOptions = () => getJson<Record<string, unknown>>('/api/raw-parsing/options')

// ── Candidates ────────────────────────────────────────────────────────────────
export interface CandidateBrainRegion {
  id: string
  generation_run_id: string
  batch_id: string
  resource_id: string
  parse_run_id: string
  raw_name: string
  std_name: string | null
  en_name: string | null
  cn_name: string | null
  laterality: string
  granularity_level: string
  granularity_family: string
  source_atlas: string
  source_version: string
  candidate_status: string
  created_at: string
  updated_at: string
}
export const fetchCandidates = (p?: {
  candidate_status?: string
  laterality?: string
  batch_id?: string
  resource_id?: string
  generation_run_id?: string
  parse_run_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<CandidateBrainRegion>>('/api/candidates/brain-regions', p)
export interface CandidateStatusSummary {
  total: number
  by_status: Array<{ candidate_status: string; count: number }>
}
export const fetchCandidateStatusSummary = (p?: { batch_id?: string; resource_id?: string }) =>
  getJson<CandidateStatusSummary>('/api/candidates/brain-regions/status-summary', p)
export const fetchCandidateOptions = () => getJson<Record<string, string[]>>('/api/candidates/options')

// ── Candidate Pools ──────────────────────────────────────────────────────────
export interface CandidatePoolMember {
  id: string
  pool_id: string
  candidate_id: string
  added_at: string
  added_by: string | null
}

export interface CandidatePool {
  id: string
  name: string | null
  resource_id: string | null
  batch_id: string | null
  source_atlas: string
  granularity_level: string
  granularity_family: string | null
  candidate_count: number
  pair_count: number
  status: string
  created_at: string
  updated_at: string
  memberships: CandidatePoolMember[]
}

export interface CandidatePoolCreateRequest {
  name?: string | null
  candidate_ids: string[]
  resource_id?: string | null
  batch_id?: string | null
  source_atlas: string
  granularity_level: string
  granularity_family?: string | null
}

export interface CandidatePoolMembersRequest {
  candidate_ids: string[]
}

export const createCandidatePool = (body: CandidatePoolCreateRequest) =>
  postJson<CandidatePool>('/api/candidates/pools', body)

export const replaceCandidatePool = (body: CandidatePoolCreateRequest) =>
  postJson<CandidatePool>('/api/candidates/pools/replace', body)

export const listCandidatePools = (params?: Record<string, string | number | undefined>) =>
  getJson<{ items: CandidatePool[]; total: number }>('/api/candidates/pools', params)

export const getCandidatePool = (poolId: string) =>
  getJson<CandidatePool>(`/api/candidates/pools/${poolId}`)

export const addPoolMembers = (poolId: string, body: CandidatePoolMembersRequest) =>
  postJson<CandidatePool>(`/api/candidates/pools/${poolId}/members`, body)

export const removePoolMembers = (poolId: string, body: CandidatePoolMembersRequest) =>
  deleteJson<CandidatePool>(`/api/candidates/pools/${poolId}/members`, undefined, body)

export const deleteCandidatePool = (poolId: string) =>
  deleteJson<void>(`/api/candidates/pools/${poolId}`)

// ── Rule Validation ───────────────────────────────────────────────────────────
export interface RuleValidationRun {
  id: string
  scope: string
  batch_id: string
  resource_id: string
  generation_run_id: string | null
  parse_run_id: string | null
  status: string
  candidate_count: number
  passed_count: number
  failed_count: number
  warning_count: number
  skipped_count: number
  created_at: string
  finished_at: string | null
}
export const fetchRuleValidationRuns = (p?: {
  batch_id?: string
  resource_id?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<RuleValidationRun>>('/api/rule-validation/runs', p)

export interface CandidateRuleValidationResult {
  id: string
  validation_run_id: string
  candidate_id: string
  batch_id: string
  overall_status: string
  error_count: number
  warning_count: number
  failed_count?: number
  created_at: string
}
export const fetchRuleValidationRunResults = (
  validationRunId: string,
  p?: { limit?: number; offset?: number },
) =>
  getJson<Paginated<CandidateRuleValidationResult>>(
    `/api/rule-validation/runs/${validationRunId}/results`,
    p,
  )
export const fetchRuleValidationOptions = () => getJson<Record<string, unknown>>('/api/rule-validation/options')

// ── Human Review ──────────────────────────────────────────────────────────────
export interface CandidateReviewRecord {
  id: string
  candidate_id: string
  batch_id: string
  resource_id: string
  generation_run_id: string
  parse_run_id: string
  action: string
  from_status: string
  to_status: string
  reviewed_by: string
  reason: string | null
  created_at: string
}
export interface PendingCandidate {
  id: string
  batch_id: string
  resource_id: string
  raw_name: string
  en_name: string | null
  cn_name: string | null
  laterality: string
  candidate_status: string
  source_atlas: string
  created_at: string
}
export const fetchPendingReviews = (p?: { batch_id?: string; resource_id?: string; limit?: number; offset?: number }) =>
  getJson<Paginated<PendingCandidate>>('/api/human-review/pending', p)
export const fetchReviewRecords = (p?: { batch_id?: string; resource_id?: string; action?: string; limit?: number; offset?: number }) =>
  getJson<Paginated<CandidateReviewRecord>>('/api/human-review/records', p)
export const fetchHumanReviewOptions = () => getJson<Record<string, unknown>>('/api/human-review/options')

// ── Promotions ────────────────────────────────────────────────────────────────
export interface PromotionRecord {
  id: string
  candidate_id: string
  final_region_id: string | null
  resource_id: string
  batch_id: string
  status: string
  from_status: string
  to_status: string
  promoted_by: string
  reason: string | null
  error_message: string | null
  created_at: string
}
export const fetchPromotionRecords = (p?: {
  batch_id?: string
  resource_id?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<PromotionRecord>>('/api/promotion/records', p)
export const fetchPromotionOptions = () => getJson<Record<string, unknown>>('/api/promotion/options')

// ── Final Regions ─────────────────────────────────────────────────────────────
export interface FinalBrainRegion {
  id: string
  candidate_id: string
  resource_id: string
  batch_id: string
  parse_run_id: string
  generation_run_id: string
  source_file_id: string
  source_raw_label_id: string
  latest_review_record_id: string | null
  latest_validation_result_id: string | null
  source_atlas: string
  source_version: string
  source_label_id: string | null
  label_value: number | null
  raw_name: string
  std_name: string | null
  en_name: string | null
  cn_name: string | null
  laterality: string
  region_base_name: string | null
  granularity_level: string
  granularity_family: string
  status: string
  promoted_by: string
  promoted_at: string
  created_at: string
  updated_at: string
}
export interface FinalRegionProvenance {
  final_region: FinalBrainRegion
  promotion_records: PromotionRecord[]
}
export const fetchFinalRegions = (p?: {
  keyword?: string
  source_atlas?: string
  laterality?: string
  granularity_level?: string
  granularity_family?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<FinalBrainRegion>>('/api/final-regions', p)
export const fetchFinalRegion = (id: string) =>
  getJson<FinalBrainRegion>(`/api/final-regions/${id}`)
export const fetchFinalRegionProvenance = (id: string) =>
  getJson<FinalRegionProvenance>(`/api/final-regions/${id}/provenance`)
export const fetchFinalRegionSummary = (p?: { resource_id?: string; batch_id?: string }) =>
  getJson<Record<string, unknown>>('/api/final-regions/summary', p)
export const fetchFinalRegionOptions = () => getJson<Record<string, unknown>>('/api/final-regions/options')

// ═══════════════════════════════════════════════════════════════════════════════
// WRITE OPERATIONS (Step 10B) — all go through backend state machine
// ═══════════════════════════════════════════════════════════════════════════════

// ── Create Resource ───────────────────────────────────────────────────────────
export interface CreateResourceBody {
  resource_code: string
  source_atlas: string
  source_version: string
  resource_type: string
  species: string
  granularity_level: string
  granularity_family: string
  template_space?: string
  cn_name?: string
  en_name?: string
  description?: string
  remark?: string
  status?: string
}
export const createResource = (body: CreateResourceBody) =>
  postJson<AtlasResource>('/api/resources', body)

export type ResourceCreate = CreateResourceBody
export interface ResourceUpdate {
  source_atlas?: string
  source_version?: string
  resource_type?: string
  species?: string
  granularity_level?: string
  granularity_family?: string
  template_space?: string
  cn_name?: string | null
  en_name?: string | null
  description?: string | null
  remark?: string | null
  status?: string
}

export const updateResource = (resourceId: string, body: ResourceUpdate) =>
  patchJson<AtlasResource>(`/api/resources/${resourceId}`, body)

export const deleteResource = (resourceId: string) =>
  deleteJson<AtlasResource>(`/api/resources/${resourceId}`)

export const restoreResource = (resourceId: string) =>
  postJson<AtlasResource>(`/api/resources/${resourceId}/restore`)

export const purgeResource = (resourceId: string) =>
  postJson<void>(`/api/resources/${resourceId}/purge`)

export interface DependencyCounts {
  resource_files: number
  file_intermediate_artifacts: number
  file_normalization_runs: number
  import_batches: number
  import_batch_files: number
  import_batch_events: number
  raw_parse_runs: number
  raw_aal3_region_labels: number
  raw_macro96_region_rows: number
  candidate_generation_runs: number
  candidate_brain_regions: number
  candidate_llm_extractions?: number
  rule_validation_runs: number
  candidate_rule_validation_results: number
  candidate_review_records: number
  promotion_records: number
  final_brain_regions: number
}

export interface ResourceDeletePreview {
  resource_id: string
  resource_code: string
  source_atlas: string
  status: string
  can_delete: boolean
  delete_mode: string
  dependency_counts: DependencyCounts
  will_release_resource_code: boolean
  resource_code_after_delete_can_be_recreated: boolean
  warnings: string[]
  required_confirmation: string
}

export interface ResourceDeleteRequest {
  confirmation_text: string
  operator: string
  reason: string
  delete_physical_files?: boolean
}

export interface DeletedCounts {
  final_brain_regions: number
  promotion_records: number
  candidate_llm_extractions?: number
  candidate_review_records: number
  candidate_rule_validation_results: number
  rule_validation_runs: number
  candidate_brain_regions: number
  candidate_generation_runs: number
  raw_macro96_region_rows: number
  raw_aal3_region_labels: number
  raw_parse_runs: number
  import_batch_events: number
  import_batch_files: number
  import_batches: number
  file_intermediate_artifacts: number
  file_normalization_runs: number
  resource_files: number
  atlas_resources: number
}

export interface ResourceDeleteResult {
  resource_id: string
  resource_code: string
  status: string
  deleted_counts: DeletedCounts
  resource_code_released: boolean
  can_recreate_resource_code: boolean
  physical_files_deleted?: boolean
  physical_files_error?: string | null
}

export const getResourceDeletePreview = (resourceId: string) =>
  getJson<ResourceDeletePreview>(`/api/resources/${resourceId}/delete-preview`)

export const destructiveDeleteResource = (resourceId: string, body: ResourceDeleteRequest) =>
  postJson<ResourceDeleteResult>(`/api/resources/${resourceId}/destructive-delete`, body)

// ── Upload File ───────────────────────────────────────────────────────────────
export const uploadResourceFile = (resourceId: string, fd: FormData) =>
  uploadForm<ResourceFile>(`/api/resources/${resourceId}/files`, fd)

// ── Create Import Batch ───────────────────────────────────────────────────────
export interface BatchFileBinding {
  file_id: string
  file_role_in_batch: string
  sort_order?: number
}
export interface CreateBatchBody {
  resource_id: string
  batch_type: string
  parser_key?: string
  batch_code?: string
  files?: BatchFileBinding[]
  description?: string
  remark?: string
}
export interface UpdateBatchBody {
  batch_code?: string
  batch_type?: string
  parser_key?: string | null
  description?: string | null
  remark?: string | null
}
export const createImportBatch = (body: CreateBatchBody) =>
  postJson<ImportBatchDetail>('/api/import-batches', body)
export const updateImportBatch = (batchId: string, body: UpdateBatchBody) =>
  patchJson<ImportBatchDetail>(`/api/import-batches/${batchId}`, body)
export const updateImportBatchFiles = (batchId: string, files: BatchFileBinding[]) =>
  patchJson<{ items: ImportBatchFileEnriched[]; total: number; warnings: string[] }>(
    `/api/import-batches/${batchId}/files`,
    { files },
  )
export const cancelImportBatch = (batchId: string) =>
  postJson<ImportBatch>(`/api/import-batches/${batchId}/cancel`)
export const cloneImportBatch = (batchId: string) =>
  postJson<ImportBatchDetail>(`/api/import-batches/${batchId}/clone`)

export interface RollbackPreviewResponse {
  batch_id: string
  batch_code: string
  resource_id: string
  parser_key: string | null
  current_status: string
  target_status: string
  supported: boolean
  will_change_status: boolean
  required_confirmation: string
  warnings: string[]
  delete_plan: Record<string, number>
  keep_plan: Record<string, number>
  dependency_counts: Record<string, number>
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  next_api?: string | null
  generated_at?: string
}

export const getImportBatchRollbackPreview = (batchId: string, targetStatus: string) =>
  getJson<RollbackPreviewResponse>(
    `/api/import-batches/${batchId}/rollback-preview`,
    { target_status: targetStatus },
  )

export interface RollbackExecuteRequest {
  target_status: string
  confirmation_text: string
  operator: string
  reason: string
  expected_delete_plan?: Record<string, number>
  expected_dependency_counts?: Record<string, number>
}

export interface RollbackExecuteResponse {
  rollback_record_id: string
  batch_id: string
  batch_code?: string
  resource_id?: string
  parser_key?: string | null
  from_status: string
  target_status: string
  status: string
  deleted_counts: Record<string, number>
  kept_counts: Record<string, number>
  batch_status: string
  warnings: string[]
  events_written?: string[]
  finished_at?: string
}

export const executeImportBatchRollback = (batchId: string, payload: RollbackExecuteRequest) =>
  postJson<RollbackExecuteResponse>(`/api/import-batches/${batchId}/rollback`, payload)

export interface RunHistorySummary {
  raw_row_count: number
  candidate_count: number
  validation_result_count: number
  review_record_count: number
  promotion_record_count: number
  final_region_count: number
}

export interface RawParseRunHistoryItem {
  id: string
  parser_key: string
  status: string
  input_count: number
  output_count: number
  raw_row_count: number
  active: boolean
  created_at?: string
  started_at?: string
  finished_at?: string
  note?: string | null
}

export interface CandidateGenerationRunHistoryItem {
  id: string
  generator_key: string
  status: string
  input_count: number
  output_count: number
  candidate_count: number
  active: boolean
  created_at?: string
  finished_at?: string
  note?: string | null
}

export interface RuleValidationRunHistoryItem {
  id: string
  status: string
  passed_count: number
  warning_count: number
  failed_count: number
  result_count: number
  active: boolean
  created_at?: string
  finished_at?: string
  note?: string | null
}

export interface RollbackRecordHistoryItem {
  id: string
  from_status: string
  target_status: string
  operator: string
  reason: string
  deleted_counts: Record<string, number>
  status: string
  created_at?: string
  finished_at?: string
}

export interface RunHistoryEventItem {
  id: string
  event_type: string
  from_status?: string | null
  to_status?: string | null
  message?: string | null
  created_at?: string
}

export interface ImportBatchRunHistoryResponse {
  batch_id: string
  batch_code: string
  resource_id: string
  parser_key?: string | null
  status: string
  summary: RunHistorySummary
  raw_parse_runs: RawParseRunHistoryItem[]
  candidate_generation_runs: CandidateGenerationRunHistoryItem[]
  rule_validation_runs: RuleValidationRunHistoryItem[]
  rollback_records: RollbackRecordHistoryItem[]
  events: RunHistoryEventItem[]
  current_active?: {
    raw_parse_run_id?: string | null
    candidate_generation_run_id?: string | null
    validation_run_id?: string | null
    rollback_record_id?: string | null
  }
  warnings?: string[]
}

export const getImportBatchRunHistory = (batchId: string) =>
  getJson<ImportBatchRunHistoryResponse>(`/api/import-batches/${batchId}/run-history`)

export const attachImportBatchFile = (batchId: string, body: BatchFileBinding) =>
  postJson<{ items: ImportBatchFileEnriched[]; total: number; warnings: string[] }>(
    `/api/import-batches/${batchId}/files`,
    body,
  )
export const updateImportBatchFileBinding = (
  batchId: string,
  fileId: string,
  body: { file_role_in_batch?: string; sort_order?: number },
) =>
  patchJson<{ items: ImportBatchFileEnriched[]; total: number; warnings: string[] }>(
    `/api/import-batches/${batchId}/files/${fileId}`,
    body,
  )
export const detachImportBatchFile = (batchId: string, fileId: string) =>
  deleteJson<{ items: ImportBatchFileEnriched[]; total: number; warnings: string[] }>(
    `/api/import-batches/${batchId}/files/${fileId}`,
  )
export const queueBatch = (batchId: string) =>
  postJson<ImportBatch>(`/api/import-batches/${batchId}/queue`)
export const startBatch = (batchId: string) =>
  postJson<ImportBatch>(`/api/import-batches/${batchId}/start`)

// ── Parse AAL3 ────────────────────────────────────────────────────────────────
export interface ParseAal3Result {
  parse_run: { id: string; status: string; batch_id: string }
  output_count: number
}
export const parseAal3 = (batchId: string) =>
  postJson<ParseAal3Result>(`/api/import-batches/${batchId}/parse-aal3`)

export interface ParseMacro96Response {
  parse_run_id: string
  batch_id: string
  resource_id: string
  source_file_id: string
  intermediate_artifact_id: string | null
  parser_key: string
  parser_version: string
  row_count: number
  warning_count: number
  status: string
}
export const parseMacro96Batch = (batchId: string) =>
  postJson<ParseMacro96Response>(`/api/import-batches/${batchId}/parse-macro96`)

export interface RawMacro96Row {
  id: string
  parse_run_id: string
  resource_id: string
  batch_id: string
  source_file_id: string
  intermediate_artifact_id: string | null
  row_index: number
  region_index: number
  en_name: string
  cn_name: string | null
  source_sheet: string | null
  raw_payload: Record<string, unknown>
  created_at: string
}
export interface RawMacro96RowListResponse {
  items: RawMacro96Row[]
  total: number
  limit: number
  offset: number
}
export const listRawMacro96Rows = (params: {
  batch_id?: string
  parse_run_id?: string
  resource_id?: string
  source_file_id?: string
  limit?: number
  offset?: number
}) => getJson<RawMacro96RowListResponse>('/api/raw-parsing/macro96-rows', params as Record<string, string | number | boolean | null | undefined>)

// ── Generate Candidates ───────────────────────────────────────────────────────
export interface GenerateCandidatesResult {
  generation_run: { id: string; status: string }
  output_count: number
  skipped_count: number
  batch_status: string
}
export const generateCandidates = (batchId: string, parseRunId?: string) =>
  postJson<GenerateCandidatesResult>(
    `/api/import-batches/${batchId}/generate-candidates`,
    undefined,
    parseRunId ? { parse_run_id: parseRunId } : undefined,
  )

export interface GenerateMacro96CandidatesResponse {
  generation_run_id: string
  batch_id: string
  resource_id: string
  parse_run_id: string
  generator_key: string
  candidate_count: number
  status: string
  batch_status: string
}
export const generateMacro96Candidates = (batchId: string, parseRunId?: string) =>
  postJson<GenerateMacro96CandidatesResponse>(
    `/api/import-batches/${batchId}/generate-macro96-candidates`,
    undefined,
    parseRunId ? { parse_run_id: parseRunId } : undefined,
  )

// ── Rule Validation ───────────────────────────────────────────────────────────
export interface ValidateResult {
  validation_run: { id: string; status: string }
  candidate_count: number
  passed_count: number
  failed_count: number
  skipped_count: number
}
export const validateByBatch = (batchId: string) =>
  postJson<ValidateResult>('/api/rule-validation/run', undefined, { batch_id: batchId })
export const validateByGenRun = (genRunId: string) =>
  postJson<ValidateResult>('/api/rule-validation/run', undefined, { generation_run_id: genRunId })
export const validateSingleCandidate = (candidateId: string) =>
  postJson<ValidateResult>(`/api/candidates/${candidateId}/validate`)

// ── Human Review ──────────────────────────────────────────────────────────────
export const submitReview = (candidateId: string, body: { reviewed_by: string; reason?: string }) =>
  postJson<unknown>(`/api/candidates/${candidateId}/submit-review`, body)
export const reviewDecision = (
  candidateId: string,
  body: { action: string; reviewed_by: string; reason?: string },
) => postJson<unknown>(`/api/candidates/${candidateId}/review`, body)

// ── Promotion ─────────────────────────────────────────────────────────────────
export interface PromoteResult {
  final_region: FinalBrainRegion
  record: PromotionRecord
}
export const promoteCandidate = (candidateId: string, body: { promoted_by: string; reason?: string }) =>
  postJson<PromoteResult>(`/api/candidates/${candidateId}/promote`, body)

// ═══════════════════════════════════════════════════════════════════════════════
// LLM EXTRACTION (MVP 2 Step 1) — DeepSeek candidate-side, advisory only.
// Output goes to candidate_llm_extractions; NEVER final_* / kg_*, no approve/promote.
// ═══════════════════════════════════════════════════════════════════════════════

export interface LlmSuggestion {
  candidate_id?: string
  suggested_cn_name?: string
  suggested_en_name?: string
  suggested_aliases?: string[]
  suggested_description?: string
  suggested_region_base_name?: string
  suggested_laterality?: string
  confidence?: number
  evidence_summary?: string
  risk_flags?: string[]
  needs_human_review?: boolean
}

export interface LlmExtraction {
  id: string
  candidate_id: string
  batch_id: string
  resource_id: string
  generation_run_id: string
  parse_run_id: string
  run_id: string
  provider: string
  model: string
  prompt_version: string
  status: 'pending' | 'succeeded' | 'failed'
  raw_response: string | null
  structured_result: LlmSuggestion | null
  error_message: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  latency_ms: number | null
  created_at: string
  updated_at: string
}

export interface LlmExtractionOptions {
  provider: string
  model: string
  prompt_version: string
  max_batch_size: number
  laterality_values: string[]
  api_key_configured: boolean
}

export interface BatchExtractResult {
  run_id: string
  requested: number
  succeeded: number
  failed: number
  items: LlmExtraction[]
}

export const fetchLlmExtractionOptions = () =>
  getJson<LlmExtractionOptions>('/api/llm-extraction/options')

export const fetchLlmExtractions = (p?: {
  candidate_id?: string
  batch_id?: string
  resource_id?: string
  run_id?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<LlmExtraction>>('/api/llm-extraction', p)

export const fetchCandidateLlmExtractions = (candidateId: string, p?: { limit?: number; offset?: number }) =>
  getJson<Paginated<LlmExtraction>>(`/api/candidates/${candidateId}/llm-extractions`, p)

export const extractCandidate = (candidateId: string) =>
  postJson<LlmExtraction>(`/api/candidates/${candidateId}/llm-extract`)

export const extractCandidatesBatch = (candidateIds: string[]) =>
  postJson<BatchExtractResult>('/api/llm-extraction/batch', { candidate_ids: candidateIds })

// ── LLM Extraction Infrastructure (Step 1) ─────────────────────────────────────

export interface LlmProviderInfo {
  name: string
  configured: boolean
  default_model: string
  enabled?: boolean
}

export interface LlmTaskTypeInfo {
  task_type: string
  label: string
  implemented: boolean
  description: string
}

export interface LlmExtractionRun {
  id: string
  task_type: string
  provider: string
  model_name: string
  prompt_template_id: string | null
  prompt_template_key: string | null
  prompt_version: string | null
  scope_type: string
  scope_json: Record<string, unknown>
  resource_id: string | null
  batch_id: string | null
  granularity_level: string | null
  granularity_family: string | null
  source_atlas: string | null
  source_version: string | null
  status: string
  input_count: number
  output_count: number
  error_count: number
  temperature: number | null
  max_tokens: number | null
  request_payload_redacted: Record<string, unknown>
  usage_json: Record<string, unknown>
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface LlmExtractionItem {
  id: string
  run_id: string
  candidate_id: string | null
  resource_id: string | null
  batch_id: string | null
  task_type: string
  item_index: number
  input_json: Record<string, unknown>
  prompt_json: Record<string, unknown>
  raw_response_text: string | null
  parsed_response_json: Record<string, unknown>
  normalized_output_json: Record<string, unknown>
  status: string
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface LlmExtractionRunDetail extends LlmExtractionRun {
  items: LlmExtractionItem[]
}

export interface RegionFieldCompletionRequest {
  provider: string
  model_name?: string | null
  candidate_ids: string[]
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
}

export interface RegionFieldCompletionResponse {
  run_id: string
  requested: number
  succeeded: number
  failed: number
  dry_run: boolean
  items: LlmExtractionItem[]
  legacy_extractions: LlmExtraction[]
}

export const listLlmProviders = () =>
  getJson<{ providers: LlmProviderInfo[] }>('/api/llm-extraction/providers')

export const listLlmTaskTypes = () =>
  getJson<{ task_types: LlmTaskTypeInfo[] }>('/api/llm-extraction/task-types')

export const listLlmExtractionRuns = (p?: {
  task_type?: string
  provider?: string
  status?: string
  resource_id?: string
  batch_id?: string
  candidate_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<LlmExtractionRun>>('/api/llm-extraction/runs', p)

export const getLlmExtractionRun = (runId: string) =>
  getJson<LlmExtractionRunDetail>(`/api/llm-extraction/runs/${runId}`)

export const listLlmExtractionItems = (p?: {
  run_id?: string
  candidate_id?: string
  task_type?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<LlmExtractionItem>>('/api/llm-extraction/items', p)

export const runRegionFieldCompletion = (body: RegionFieldCompletionRequest) =>
  postJson<RegionFieldCompletionResponse>('/api/llm-extraction/region-field-completion', body)

// ── Universal Field Completion (Step 10.3) — mirror/candidate only ─────────────

export type FieldCompletionTargetType =
  | 'candidate_region'
  | 'projection'
  | 'region_function'
  | 'circuit'
  | 'circuit_step'
  | 'projection_function'
  | 'circuit_function'
  | 'circuit_projection_membership'
  | 'triple'
  | 'evidence'

export type FieldCompletionScope = 'missing_only' | 'selected_fields' | 'all_enrichable_fields'
export type FieldCompletionOverwritePolicy = 'fill_missing_only' | 'suggest_only' | 'overwrite_with_review'

export interface UniversalFieldCompletionRequest {
  provider?: string
  model_name?: string | null
  target_type: FieldCompletionTargetType
  target_ids: string[]
  field_scope?: FieldCompletionScope
  selected_fields?: string[]
  dry_run?: boolean
  create_mirror_updates?: boolean
  create_evidence?: boolean
  overwrite_policy?: FieldCompletionOverwritePolicy
  include_existing_evidence?: boolean
  include_related_objects?: boolean
  include_provenance?: boolean
  prompt_template_key?: string
  prompt_overrides?: Record<string, string>
  temperature?: number
  max_tokens?: number
}

export interface FieldCompletionUpdateSummary {
  target_id: string
  field_name: string
  update_status: string
  suggested_value?: unknown
  applied_value?: unknown
}

export interface UniversalFieldCompletionResponse {
  run_id: string
  status: string
  provider: string
  model_name: string | null
  target_type: FieldCompletionTargetType
  target_count: number
  updated_count: number
  suggested_count: number
  skipped_count: number
  failed_count: number
  applied_direct_count?: number
  applied_overlay_count?: number
  summary_json?: Record<string, number>
  field_updates: FieldCompletionUpdateSummary[]
  prompt_preview?: Record<string, unknown> | null
  warnings: string[]
  errors: string[]
  dry_run: boolean
}

export interface FieldCompletionRun {
  id: string
  provider: string
  model_name: string | null
  target_type: string
  target_count: number
  field_scope: string
  selected_fields_json: unknown[]
  overwrite_policy: string
  dry_run: boolean
  create_mirror_updates: boolean
  create_evidence: boolean
  status: string
  request_json: Record<string, unknown>
  summary_json: Record<string, unknown>
  warnings_json: unknown[]
  errors_json: unknown[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
}

export interface FieldCompletionItem {
  id: string
  run_id: string
  target_type: string
  target_id: string
  field_name: string
  old_value_json?: unknown
  suggested_value_json?: unknown
  applied_value_json?: unknown
  confidence?: number | null
  evidence_text?: string | null
  reasoning_summary?: string | null
  uncertainty_reason?: string | null
  update_status: string
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface FieldCompletionRunDetail extends FieldCompletionRun {
  items: FieldCompletionItem[]
}

export const runUniversalFieldCompletion = (body: UniversalFieldCompletionRequest) =>
  postJson<UniversalFieldCompletionResponse>('/api/llm-extraction/field-completion/run', body)

export const listFieldCompletionRuns = (p?: {
  target_type?: FieldCompletionTargetType
  status?: string
  provider?: string
  limit?: number
  offset?: number
}) => getJson<{ items: FieldCompletionRun[]; total: number }>('/api/llm-extraction/field-completion/runs', p)

export const getFieldCompletionRun = (runId: string) =>
  getJson<FieldCompletionRunDetail>(`/api/llm-extraction/field-completion/runs/${runId}`)

export const listFieldCompletionItems = (p?: {
  run_id?: string
  target_type?: FieldCompletionTargetType
  target_id?: string
  field_name?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<{ items: FieldCompletionItem[]; total: number }>('/api/llm-extraction/field-completion/items', p)

export interface FieldCompletionRelatedGroup {
  target_type: FieldCompletionTargetType | string
  target_ids: string[]
  count: number
  warnings?: string[]
}

export interface FieldCompletionRelatedTargetsResponse {
  source_target_type: string
  source_target_ids: string[]
  groups: FieldCompletionRelatedGroup[]
  warnings?: string[]
}

export const getFieldCompletionRelatedTargets = (p: {
  target_type: 'circuit'
  target_ids: string[]
  include?: string[]
}) =>
  getJson<FieldCompletionRelatedTargetsResponse>(
    '/api/llm-extraction/field-completion/related-targets',
    {
      target_type: p.target_type,
      target_ids: p.target_ids.join(','),
      include: (p.include ?? ['circuit_step', 'circuit_function']).join(','),
    },
  )

export interface FieldCompletionPromptTemplate {
  key: string
  title: string
  display_name: string | null
  target_type: string | null
  field_name: string | null
  template: string
  system_prompt: string
}

export const getFieldCompletionPromptTemplates = () =>
  getJson<{ items: FieldCompletionPromptTemplate[] }>(
    '/api/llm-extraction/field-completion/prompt-templates',
  )

export interface ExtractionPromptTemplate {
  key: string
  title: string
  display_name: string | null
  category: string
  target_type: string | null
  field_name: string | null
  description: string | null
  template: string
  system_prompt: string
}

export const getExtractionPromptTemplates = (category = 'extraction') =>
  getJson<{ items: ExtractionPromptTemplate[] }>(
    '/api/llm-extraction/prompt-templates',
    { category },
  )

// ── Mirror KG (Step 2) — precursor layer, NOT final_* ─────────────────────────

export interface MirrorRegionConnection {
  id: string
  source_region_candidate_id: string | null
  target_region_candidate_id: string | null
  source_region_final_id: string | null
  target_region_final_id: string | null
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  connection_type: string
  directionality: string
  strength: string | null
  modality: string | null
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  raw_payload_json: Record<string, unknown>
  normalized_payload_json: Record<string, unknown>
  attributes?: Record<string, unknown>
  created_by: string | null
  updated_by: string | null
  created_at: string
  updated_at: string
}

export interface MirrorRegionFunction {
  id: string
  region_candidate_id: string | null
  region_final_id: string | null
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  function_term: string
  function_category: string
  relation_type: string
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  raw_payload_json?: Record<string, unknown>
  normalized_payload_json?: Record<string, unknown>
  attributes?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface MirrorCircuitRegion {
  id: string
  circuit_id: string
  region_candidate_id: string | null
  role: string
  sort_order: number
  created_at: string
}

export interface MirrorRegionCircuit {
  id: string
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  circuit_name: string
  circuit_type: string
  function_association: string | null
  description: string | null
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  raw_payload_json?: Record<string, unknown>
  normalized_payload_json?: Record<string, unknown>
  attributes?: Record<string, unknown>
  created_at: string
  updated_at: string
  circuit_regions?: MirrorCircuitRegion[]
}

export interface MirrorKgTriple {
  id: string
  subject_type: string
  subject_id: string | null
  subject_label: string
  predicate: string
  object_type: string
  object_id: string | null
  object_label: string
  triple_scope: string
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  created_at: string
  updated_at: string
}

export interface MirrorEvidenceRecord {
  id: string
  evidence_target_type: string
  evidence_target_id: string
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  evidence_type: string
  evidence_text: string
  confidence: number | null
  uncertainty_reason: string | null
  created_at: string
}

export const listMirrorConnections = (p?: {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  mirror_status?: string
  review_status?: string
  llm_run_id?: string
  llm_item_id?: string
  candidate_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorRegionConnection>>('/api/mirror-kg/connections', p)

export const getMirrorConnection = (id: string) =>
  getJson<MirrorRegionConnection>(`/api/mirror-kg/connections/${id}`)

export const createMirrorConnection = (body: Partial<MirrorRegionConnection>) =>
  postJson<MirrorRegionConnection>('/api/mirror-kg/connections', body)

export const updateMirrorConnection = (id: string, body: Record<string, unknown>) =>
  patchJson<MirrorRegionConnection>(`/api/mirror-kg/connections/${id}`, body)

export const deleteMirrorConnection = (id: string) =>
  deleteJson<void>(`/api/mirror-kg/connections/${id}`)

export const listMirrorFunctions = (p?: {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  mirror_status?: string
  review_status?: string
  llm_run_id?: string
  candidate_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorRegionFunction>>('/api/mirror-kg/functions', p)

export const getMirrorFunction = (id: string) =>
  getJson<MirrorRegionFunction>(`/api/mirror-kg/functions/${id}`)

export const createMirrorFunction = (body: Partial<MirrorRegionFunction>) =>
  postJson<MirrorRegionFunction>('/api/mirror-kg/functions', body)

export const updateMirrorFunction = (id: string, body: Record<string, unknown>) =>
  patchJson<MirrorRegionFunction>(`/api/mirror-kg/functions/${id}`, body)

export const deleteMirrorFunction = (id: string) =>
  deleteJson<void>(`/api/mirror-kg/functions/${id}`)

export const listMirrorCircuits = (p?: {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  mirror_status?: string
  review_status?: string
  llm_run_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorRegionCircuit>>('/api/mirror-kg/circuits', p)

export const getMirrorCircuit = (id: string) =>
  getJson<MirrorRegionCircuit>(`/api/mirror-kg/circuits/${id}`)

export const createMirrorCircuit = (body: Partial<MirrorRegionCircuit>) =>
  postJson<MirrorRegionCircuit>('/api/mirror-kg/circuits', body)

export const updateMirrorCircuit = (id: string, body: Record<string, unknown>) =>
  patchJson<MirrorRegionCircuit>(`/api/mirror-kg/circuits/${id}`, body)

export const deleteMirrorCircuit = (id: string) =>
  deleteJson<void>(`/api/mirror-kg/circuits/${id}`)

export const listMirrorTriples = (p?: {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  mirror_status?: string
  review_status?: string
  predicate?: string
  llm_run_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorKgTriple>>('/api/mirror-kg/triples', p)

export const getMirrorTriple = (id: string) =>
  getJson<MirrorKgTriple>(`/api/mirror-kg/triples/${id}`)

export const createMirrorTriple = (body: Partial<MirrorKgTriple>) =>
  postJson<MirrorKgTriple>('/api/mirror-kg/triples', body)

export interface MirrorTripleConsolidationRequest {
  source_types?: Array<'connection' | 'function' | 'circuit'>
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    granularity_level?: string
    granularity_family?: string
  }
  mirror_status?: string[]
  review_status?: string[]
  promotion_status?: string[]
  connection_ids?: string[]
  function_ids?: string[]
  circuit_ids?: string[]
  include_existing?: boolean
  dry_run?: boolean
  limit?: number
}

export interface MirrorTriplePreviewItem {
  subject_type: string
  subject_id?: string | null
  subject_label: string
  predicate: string
  object_type: string
  object_id?: string | null
  object_label: string
  source_type: string
  source_id: string
  confidence?: number | null
  evidence_text?: string | null
  duplicate?: boolean
}

export interface MirrorTripleConsolidationResponse {
  dry_run: boolean
  source_counts: Record<string, number>
  planned_triple_count: number
  created_triple_count: number
  skipped_duplicate_count: number
  skipped_invalid_count: number
  existing_triple_count?: number
  created_triple_ids?: string[]
  triples_preview?: MirrorTriplePreviewItem[]
  warnings?: string[]
}

export const consolidateMirrorTriples = (payload: MirrorTripleConsolidationRequest) =>
  postJson<MirrorTripleConsolidationResponse>('/api/mirror-kg/triples/consolidate', payload)

// ── Mirror KG Macro Clinical (Step 8.6) — schema foundation ───────────────────

export interface MirrorCircuitStep {
  id: string
  circuit_id: string
  region_candidate_id: string | null
  region_final_id: string | null
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  step_order: number
  step_name: string
  step_type: string
  role: string
  description: string | null
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  raw_payload_json?: Record<string, unknown>
  normalized_payload_json?: Record<string, unknown>
  attributes?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface MirrorProjectionFunction {
  id: string
  projection_id: string
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  function_term: string
  function_category: string
  relation_type: string
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  raw_payload_json?: Record<string, unknown>
  normalized_payload_json?: Record<string, unknown>
  attributes?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface MirrorCircuitFunction {
  id: string
  circuit_id: string
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  primary_evidence_id: string | null
  external_code: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  function_term_en: string | null
  function_term_cn: string | null
  function_domain: string | null
  function_role: string | null
  effect_type: string | null
  confidence_score: number | null
  evidence_level: string | null
  description: string | null
  remark: string | null
  attributes: Record<string, unknown>
  source_db: string | null
  status: string | null
  mirror_status: string
  review_status: string
  validation_status: string | null
  promotion_status: string
  confidence: number | null
  evidence_text: string | null
  provenance: string | null
  uncertainty_reason: string | null
  raw_payload_json?: Record<string, unknown>
  normalized_payload_json?: Record<string, unknown>
  created_by: string | null
  updated_by: string | null
  created_at: string
  updated_at: string
}

export interface MirrorCircuitFunctionListResponse extends Paginated<MirrorCircuitFunction> {
  warnings?: string[]
}

export function isMirrorCircuitFunctionsNotInitialized(err: unknown): boolean {
  if (err instanceof ApiError && err.status === 503) {
    const body = err.meta?.responseBody as { detail?: { code?: string } | string } | undefined
    const detail = body?.detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      return detail.code === 'MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED'
    }
  }
  const msg = err instanceof Error ? err.message : String(err ?? '')
  return msg.includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
}

export interface MirrorCircuitProjectionMembership {
  id: string
  circuit_id: string
  projection_id: string
  source_step_id: string | null
  target_step_id: string | null
  resource_id: string | null
  batch_id: string | null
  llm_run_id: string | null
  llm_item_id: string | null
  granularity_level: string
  granularity_family: string | null
  source_atlas: string
  source_version: string | null
  step_order: number | null
  role_in_circuit: string
  source_method: string
  verification_status: string
  confidence: number | null
  evidence_text: string | null
  uncertainty_reason: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  created_at: string
  updated_at: string
}

export interface MirrorDualModelVerificationRun {
  id: string
  verification_task_type: string
  model_a_provider: string
  model_a_name: string | null
  model_a_run_id: string | null
  model_b_provider: string
  model_b_name: string | null
  model_b_run_id: string | null
  scope_json: Record<string, unknown>
  resource_id: string | null
  batch_id: string | null
  source_atlas: string | null
  source_version: string | null
  granularity_level: string | null
  granularity_family: string | null
  status: string
  object_count: number
  consensus_supported_count: number
  consensus_rejected_count: number
  model_conflict_count: number
  insufficient_information_count: number
  needs_human_review_count: number
  dry_run: boolean
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface MirrorDualModelVerificationResult {
  id: string
  run_id: string
  object_type: string
  object_id: string
  model_a_provider: string
  model_a_decision: string
  model_a_confidence: number | null
  model_b_provider: string
  model_b_decision: string
  model_b_confidence: number | null
  consensus_status: string
  consensus_score: number | null
  conflict_summary: string | null
  recommended_review_priority: string
  evidence_text: string | null
  uncertainty_reason: string | null
  source_atlas: string | null
  granularity_level: string | null
  created_at: string
}

export const listMirrorCircuitSteps = (p?: {
  circuit_id?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorCircuitStep>>('/api/mirror-kg/circuit-steps', p)

export const getMirrorCircuitStep = (id: string) =>
  getJson<MirrorCircuitStep>(`/api/mirror-kg/circuit-steps/${id}`)

export const createMirrorCircuitStep = (body: Partial<MirrorCircuitStep>) =>
  postJson<MirrorCircuitStep>('/api/mirror-kg/circuit-steps', body)

export const listMirrorProjectionFunctions = (p?: {
  projection_id?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorProjectionFunction>>('/api/mirror-kg/projection-functions', p)

export const getMirrorProjectionFunction = (id: string) =>
  getJson<MirrorProjectionFunction>(`/api/mirror-kg/projection-functions/${id}`)

export const createMirrorProjectionFunction = (body: Partial<MirrorProjectionFunction>) =>
  postJson<MirrorProjectionFunction>('/api/mirror-kg/projection-functions', body)

export const listMirrorCircuitFunctions = (p?: {
  circuit_id?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  granularity_family?: string
  function_domain?: string
  function_role?: string
  effect_type?: string
  mirror_status?: string
  review_status?: string
  validation_status?: string
  promotion_status?: string
  status?: string
  llm_run_id?: string
  q?: string
  limit?: number
  offset?: number
}) => getJson<MirrorCircuitFunctionListResponse>('/api/mirror-kg/circuit-functions', p)

export const getMirrorCircuitFunction = (id: string) =>
  getJson<MirrorCircuitFunction>(`/api/mirror-kg/circuit-functions/${id}`)

export type PromotionReadiness = 'ready' | 'needs_review' | 'blocked'

export interface CircuitFunctionPromotionPreview {
  target_type: string
  source_id: string
  source_table: string
  formal_table: string
  formal_payload_preview: Record<string, unknown>
  readiness: PromotionReadiness
  blocking_reasons: string[]
  warnings: string[]
  missing_required_fields: string[]
  review_status: string
  promotion_status: string
  actual_promotion_allowed: boolean
}

export interface CircuitFunctionPromotionCandidateItem {
  id: string
  circuit_id: string
  function_term_en?: string | null
  function_term_cn?: string | null
  function_domain?: string | null
  function_role?: string | null
  effect_type?: string | null
  confidence_score?: number | null
  evidence_level?: string | null
  review_status: string
  promotion_status: string
  validation_status?: string | null
  status?: string | null
  readiness: PromotionReadiness
  missing_required_fields: string[]
  warnings: string[]
}

export interface CircuitFunctionPromotionCandidateListResponse {
  target_type: string
  source_table: string
  formal_table: string
  items: CircuitFunctionPromotionCandidateItem[]
  total: number
  limit: number
  offset: number
  warnings?: string[]
}

export const listCircuitFunctionPromotionCandidates = (p?: {
  circuit_id?: string
  resource_id?: string
  batch_id?: string
  review_status?: string
  promotion_status?: string
  limit?: number
  offset?: number
}) => getJson<CircuitFunctionPromotionCandidateListResponse>(
  '/api/mirror-kg/promotion-candidates',
  { target_type: 'circuit_function', ...p },
)

export const fetchCircuitFunctionPromotionPreview = (sourceId: string) =>
  getJson<CircuitFunctionPromotionPreview>(
    `/api/mirror-kg/promotion-candidates/circuit_function/${sourceId}/preview`,
  )

export const listMirrorCircuitProjectionMemberships = (p?: {
  circuit_id?: string
  projection_id?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorCircuitProjectionMembership>>('/api/mirror-kg/circuit-projection-memberships', p)

export const getMirrorCircuitProjectionMembership = (id: string) =>
  getJson<MirrorCircuitProjectionMembership>(`/api/mirror-kg/circuit-projection-memberships/${id}`)

export const createMirrorCircuitProjectionMembership = (body: Partial<MirrorCircuitProjectionMembership>) =>
  postJson<MirrorCircuitProjectionMembership>('/api/mirror-kg/circuit-projection-memberships', body)

export const listMirrorDualModelVerificationRuns = (p?: {
  verification_task_type?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorDualModelVerificationRun>>('/api/mirror-kg/dual-model-verification/runs', p)

export const getMirrorDualModelVerificationRun = (id: string) =>
  getJson<MirrorDualModelVerificationRun>(`/api/mirror-kg/dual-model-verification/runs/${id}`)

export const createMirrorDualModelVerificationRun = (body: Partial<MirrorDualModelVerificationRun>) =>
  postJson<MirrorDualModelVerificationRun>('/api/mirror-kg/dual-model-verification/runs', body)

export const listMirrorDualModelVerificationResults = (p?: {
  run_id?: string
  object_type?: string
  object_id?: string
  consensus_status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorDualModelVerificationResult>>('/api/mirror-kg/dual-model-verification/results', p)

export const getMirrorDualModelVerificationResult = (id: string) =>
  getJson<MirrorDualModelVerificationResult>(`/api/mirror-kg/dual-model-verification/results/${id}`)

export const createMirrorDualModelVerificationResult = (body: Partial<MirrorDualModelVerificationResult>) =>
  postJson<MirrorDualModelVerificationResult>('/api/mirror-kg/dual-model-verification/results', body)

export interface MirrorValidationScope {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  source_version?: string
  granularity_level?: string
  granularity_family?: string
  mirror_status?: string[]
  review_status?: string[]
  promotion_status?: string[]
}

export interface MirrorValidationFilters {
  circuit_id?: string
  projection_id?: string
  object_type?: string
  validation_status?: string
  consensus_status?: string
  verification_status?: string
}

export type MirrorValidationTargetType =
  | 'connection'
  | 'function'
  | 'circuit'
  | 'triple'
  | 'projection'
  | 'circuit_step'
  | 'projection_function'
  | 'circuit_projection_membership'
  | 'circuit_projection_cross_validation_result'
  | 'dual_model_verification_result'

export interface MirrorValidationRequest {
  target_types: MirrorValidationTargetType[]
  scope?: MirrorValidationScope
  filters?: MirrorValidationFilters
  connection_ids?: string[]
  function_ids?: string[]
  circuit_ids?: string[]
  triple_ids?: string[]
  projection_ids?: string[]
  circuit_step_ids?: string[]
  projection_function_ids?: string[]
  membership_ids?: string[]
  cross_validation_result_ids?: string[]
  dual_model_result_ids?: string[]
  dry_run?: boolean
  apply_status_update?: boolean
  limit?: number
}

export interface MirrorValidationResultPreview {
  target_type: string
  target_id: string
  rule_code: string
  severity: string
  status: string
  message: string
  details_json?: Record<string, unknown>
}

export interface MirrorValidationResponse {
  dry_run: boolean
  run_id?: string | null
  target_counts: Record<string, number>
  passed_count: number
  warning_count: number
  failed_count: number
  blocked_count: number
  high_review_priority_count?: number
  result_count: number
  status_updates?: Record<string, number>
  results_preview?: MirrorValidationResultPreview[]
  warnings?: string[]
}

export interface MirrorValidationRun {
  id: string
  target_types: string[]
  scope_json: Record<string, unknown>
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  status: string
  object_count: number
  passed_count: number
  warning_count: number
  failed_count: number
  blocked_count: number
  result_count: number
  dry_run: boolean
  apply_status_update: boolean
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
}

export interface MirrorValidationResult {
  id: string
  run_id: string
  target_type: string
  target_id: string
  rule_code: string
  severity: string
  status: string
  message: string
  details_json: Record<string, unknown>
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  created_at: string
}

export const runMirrorValidation = (payload: MirrorValidationRequest) =>
  postJson<MirrorValidationResponse>('/api/mirror-kg/validation/run', payload)

export const listMirrorValidationRuns = (p?: {
  target_type?: string
  status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorValidationRun>>('/api/mirror-kg/validation/runs', p)

export const getMirrorValidationRun = (runId: string) =>
  getJson<MirrorValidationRun & { results_summary?: Record<string, number> }>(
    `/api/mirror-kg/validation/runs/${runId}`,
  )

export const listMirrorValidationResults = (p?: {
  run_id?: string
  target_type?: string
  target_id?: string
  severity?: string
  status?: string
  rule_code?: string
  resource_id?: string
  batch_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorValidationResult>>('/api/mirror-kg/validation/results', p)

export interface MirrorReviewQueueParams {
  target_types?: string[]
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  granularity_family?: string
  mirror_status?: string[]
  review_status?: string[]
  promotion_status?: string[]
  has_blocker?: boolean
  has_error?: boolean
  has_warning?: boolean
  has_model_conflict?: boolean
  has_cross_conflict?: boolean
  consensus_status?: string
  verification_status?: string
  recommended_review_priority?: string
  limit?: number
  offset?: number
  search?: string
}

export type MirrorReviewTargetType =
  | 'connection' | 'function' | 'region_function' | 'circuit' | 'triple'
  | 'projection' | 'circuit_step' | 'projection_function'
  | 'circuit_projection_membership'
  | 'circuit_projection_cross_validation_result'
  | 'dual_model_verification_result'

export type MirrorReviewActionType =
  | 'approve' | 'reject' | 'needs_revision' | 'edit' | 'comment'
  | 'accept_signal' | 'dismiss_signal' | 'flag_for_followup'

export interface MirrorReviewGating {
  can_approve: boolean
  can_reject: boolean
  can_edit: boolean
  can_comment: boolean
  can_accept_signal: boolean
  can_dismiss_signal: boolean
  gating_reasons: string[]
  requires_reviewer_reason: boolean
}

export interface MirrorReviewQueueItem {
  target_type: string
  target_id: string
  display_label: string
  target_label?: string
  summary?: string
  target_summary?: string
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  mirror_status: string
  review_status: string
  promotion_status: string
  confidence?: number | null
  evidence_text?: string | null
  uncertainty_reason?: string | null
  latest_validation_summary?: Record<string, unknown>
  evidence_count?: number
  llm_run_id?: string | null
  llm_item_id?: string | null
  recommended_review_priority?: string
  blocker_count?: number
  error_count?: number
  warning_count?: number
  info_count?: number
  consensus_status?: string | null
  verification_status?: string | null
  cross_validation_status?: string | null
  can_approve?: boolean
  gating_reasons?: string[]
  object_category?: string
  created_at?: string
  updated_at?: string
}

export interface MirrorReviewDetail {
  target_type: string
  target_id: string
  object_json: Record<string, unknown>
  object_payload?: Record<string, unknown>
  evidence_records: Record<string, unknown>[]
  validation_results: Record<string, unknown>[]
  cross_validation_results?: Record<string, unknown>[]
  dual_model_results?: Record<string, unknown>[]
  related_objects?: Record<string, unknown>
  review_records: Record<string, unknown>[]
  llm_trace: Record<string, unknown>
  editable_fields: string[]
  allowed_actions: string[]
  latest_validation_summary: Record<string, unknown>
  gating?: MirrorReviewGating
  recommended_review_priority?: string
  object_category?: string
}

export interface MirrorReviewActionRequest {
  target_type: string
  target_id: string
  action: MirrorReviewActionType
  reviewer: string
  reviewer_note?: string
  edit_patch_json?: Record<string, unknown>
  allow_with_warnings?: boolean
  acknowledge_risk_flags?: boolean
}

export interface MirrorReviewTargetTypeInfo {
  target_type: string
  label: string
  category: string
  supported_actions: string[]
  description: string
}

export interface MirrorReviewActionResponse {
  review_record_id: string
  target_type: string
  target_id: string
  action: string
  from_mirror_status?: string | null
  to_mirror_status?: string | null
  from_review_status?: string | null
  to_review_status?: string | null
  promotion_status?: string | null
  updated_object?: Record<string, unknown>
  warnings?: string[]
}

export interface MirrorReviewRecord {
  id: string
  target_type: string
  target_id: string
  action: string
  reviewer: string
  reviewer_note?: string | null
  created_at: string
}

export const listMirrorReviewQueue = (p?: MirrorReviewQueueParams) => {
  const q: Record<string, string | number | boolean | null | undefined> = {}
  if (p) {
    if (p.resource_id) q.resource_id = p.resource_id
    if (p.batch_id) q.batch_id = p.batch_id
    if (p.source_atlas) q.source_atlas = p.source_atlas
    if (p.granularity_level) q.granularity_level = p.granularity_level
    if (p.granularity_family) q.granularity_family = p.granularity_family
    if (p.target_types?.length) q.target_types = p.target_types.join(',')
    if (p.mirror_status?.length) q.mirror_status = p.mirror_status.join(',')
    if (p.review_status?.length) q.review_status = p.review_status.join(',')
    if (p.promotion_status?.length) q.promotion_status = p.promotion_status.join(',')
    if (p.has_blocker != null) q.has_blocker = p.has_blocker
    if (p.has_error != null) q.has_error = p.has_error
    if (p.has_warning != null) q.has_warning = p.has_warning
    if (p.has_model_conflict != null) q.has_model_conflict = p.has_model_conflict
    if (p.has_cross_conflict != null) q.has_cross_conflict = p.has_cross_conflict
    if (p.consensus_status) q.consensus_status = p.consensus_status
    if (p.verification_status) q.verification_status = p.verification_status
    if (p.recommended_review_priority) q.recommended_review_priority = p.recommended_review_priority
    if (p.search) q.search = p.search
    if (p.limit != null) q.limit = p.limit
    if (p.offset != null) q.offset = p.offset
  }
  return getJson<Paginated<MirrorReviewQueueItem>>('/api/mirror-kg/review/queue', q)
}

export const getMirrorReviewDetail = (targetType: string, targetId: string) =>
  getJson<MirrorReviewDetail>(`/api/mirror-kg/review/detail/${targetType}/${targetId}`)

export const submitMirrorReviewAction = (payload: MirrorReviewActionRequest) =>
  postJson<MirrorReviewActionResponse>('/api/mirror-kg/review/action', payload)

export const listMirrorReviewRecords = (p?: {
  target_type?: string
  target_id?: string
  action?: string
  reviewer?: string
  resource_id?: string
  batch_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorReviewRecord>>('/api/mirror-kg/review/records', p)

export const listMirrorReviewTargetTypes = () =>
  getJson<{ items: MirrorReviewTargetTypeInfo[] }>('/api/mirror-kg/review/target-types')

// ── Final Macro Clinical Promotion (Step 8.15) ───────────────────────────────
export type FinalMacroClinicalTargetType =
  | 'circuit' | 'circuit_step' | 'projection' | 'projection_function'
  | 'circuit_projection_membership' | 'region_function' | 'function'
  | 'circuit_function' | 'triple' | 'evidence'

export interface FinalMacroClinicalPromotionScope {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  source_version?: string
  granularity_level?: string
  granularity_family?: string
}

export interface FinalMacroClinicalPromotionRequest {
  target_types: FinalMacroClinicalTargetType[]
  scope?: FinalMacroClinicalPromotionScope
  mirror_object_ids?: string[]
  dry_run?: boolean
  confirm_text?: string
  allow_projection_without_membership?: boolean
  allow_conflict_with_human_reason?: boolean
  promote_dependencies?: boolean
  promote_triples?: boolean
  promote_evidence?: boolean
  promote_circuit_function_association?: boolean
  limit?: number
  created_by?: string
}

export interface FinalMacroClinicalPromotionRecordPreview {
  target_type: string
  mirror_object_id: string
  final_table?: string | null
  final_object_id?: string | null
  action: string
  eligibility_status: string
  reason?: string | null
  risk_flags?: string[]
  error_message?: string | null
  duplicate_of_final_id?: string | null
}

export interface FinalMacroClinicalPromotionResponse {
  run_id?: string | null
  dry_run: boolean
  candidate_count: number
  eligible_count: number
  promoted_count: number
  skipped_count: number
  failed_count: number
  blocked_count: number
  duplicate_count: number
  risk_flag_count: number
  records_preview: FinalMacroClinicalPromotionRecordPreview[]
  warnings?: string[]
  required_confirm_text: string
}

export interface FinalMacroClinicalPromotionRun {
  id: string
  status: string
  dry_run: boolean
  candidate_count: number
  eligible_count: number
  promoted_count: number
  skipped_count: number
  failed_count: number
  blocked_count: number
  duplicate_count: number
  risk_flag_count: number
  created_at: string
  created_by?: string | null
}

export interface FinalMacroClinicalObject {
  id: string
  final_uid?: string | null
  source_mirror_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  label?: string | null
  confidence?: number | null
  final_status: string
  created_at?: string
}

export const runFinalMacroClinicalPromotion = (payload: FinalMacroClinicalPromotionRequest) =>
  postJson<FinalMacroClinicalPromotionResponse>('/api/final-macro-clinical/promotion/run', payload)

export const listFinalMacroClinicalPromotionRuns = (p?: { status?: string; limit?: number; offset?: number }) =>
  getJson<Paginated<FinalMacroClinicalPromotionRun>>('/api/final-macro-clinical/promotion/runs', p)

export const getFinalMacroClinicalPromotionRun = (runId: string) =>
  getJson<FinalMacroClinicalPromotionRun>(`/api/final-macro-clinical/promotion/runs/${runId}`)

export const listFinalMacroClinicalPromotionRecords = (p?: {
  run_id?: string
  target_type?: string
  mirror_object_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<FinalMacroClinicalPromotionRecordPreview>>('/api/final-macro-clinical/promotion/records', p)

export const listFinalMacroClinicalObjects = (targetType: string, p?: { source_mirror_id?: string; limit?: number; offset?: number }) =>
  getJson<Paginated<FinalMacroClinicalObject>>(`/api/final-macro-clinical/objects/${targetType}`, p)

export const getFinalMacroClinicalObject = (targetType: string, finalId: string) =>
  getJson<FinalMacroClinicalObject>(`/api/final-macro-clinical/objects/${targetType}/${finalId}`)

// ── Final Macro Clinical Browser (Step 8.16, read-only) ─────────────────────
export type FinalBrowserTargetType =
  | 'region'
  | 'region_function'
  | 'circuit'
  | 'circuit_step'
  | 'circuit_function'
  | 'projection'
  | 'projection_function'
  | 'circuit_projection_membership'
  | 'triple'
  | 'evidence'

export interface FinalBrowserSearchItem {
  target_type: string
  final_id: string
  final_uid?: string | null
  label: string
  summary?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  confidence?: number | null
  final_status?: string | null
  source_mirror_type?: string | null
  source_mirror_id?: string | null
  promotion_run_id?: string | null
  created_at?: string | null
}

export interface FinalBrowserSearchResponse {
  items: FinalBrowserSearchItem[]
  total: number
  limit: number
  offset: number
  warnings?: string[]
}

export interface FinalGraphNode {
  id: string
  type: string
  label: string
  final_id?: string | null
  source_mirror_id?: string | null
  metadata?: Record<string, unknown>
}

export interface FinalGraphEdge {
  id: string
  type: string
  source: string
  target: string
  label?: string | null
  predicate?: string | null
  final_id?: string | null
  metadata?: Record<string, unknown>
}

export interface FinalGraphResponse {
  nodes: FinalGraphNode[]
  edges: FinalGraphEdge[]
  center_node_id?: string | null
  warnings?: string[]
}

export interface FinalProvenancePayload {
  source_mirror_type?: string | null
  source_mirror_id?: string | null
  promotion_run_id?: string | null
  promotion_record_id?: string | null
  promotion_record?: Record<string, unknown> | null
  validation_summary_json?: Record<string, unknown>
  review_summary_json?: Record<string, unknown>
  cross_validation_summary_json?: Record<string, unknown>
  dual_model_summary_json?: Record<string, unknown>
  provenance_json?: Record<string, unknown>
  final_status?: string | null
  created_at?: string | null
  updated_at?: string | null
  mirror_link_available?: boolean
}

export interface FinalRegionNeighborhoodResponse {
  region_candidate_id: string
  region_label?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  region_functions: Record<string, unknown>[]
  circuits: Record<string, unknown>[]
  circuit_steps: Record<string, unknown>[]
  outgoing_projections: Record<string, unknown>[]
  incoming_projections: Record<string, unknown>[]
  undirected_projections: Record<string, unknown>[]
  projection_functions: Record<string, unknown>[]
  triples: Record<string, unknown>[]
  evidence: Record<string, unknown>[]
  graph: FinalGraphResponse
}

export interface FinalCircuitDetailResponse {
  circuit: Record<string, unknown>
  steps: Record<string, unknown>[]
  memberships: Record<string, unknown>[]
  projections: Record<string, unknown>[]
  participant_regions: Record<string, unknown>[]
  circuit_functions: Record<string, unknown>[]
  projection_functions_summary: Record<string, unknown>[]
  triples: Record<string, unknown>[]
  evidence: Record<string, unknown>[]
  provenance: FinalProvenancePayload
  graph: FinalGraphResponse
}

export interface FinalProjectionDetailResponse {
  projection: Record<string, unknown>
  source_region?: Record<string, unknown> | null
  target_region?: Record<string, unknown> | null
  memberships: Record<string, unknown>[]
  circuits: Record<string, unknown>[]
  projection_functions: Record<string, unknown>[]
  triples: Record<string, unknown>[]
  evidence: Record<string, unknown>[]
  provenance: FinalProvenancePayload
  graph: FinalGraphResponse
}

export interface FinalObjectDetailResponse {
  target_type: string
  final_id: string
  object: Record<string, unknown>
  related_objects: Record<string, unknown>[]
  triples: Record<string, unknown>[]
  evidence: Record<string, unknown>[]
  provenance: FinalProvenancePayload
  promotion_record?: Record<string, unknown> | null
  warnings?: string[]
}

export const searchFinalKgObjects = (p?: {
  query?: string
  target_types?: string[]
  source_atlas?: string
  granularity_level?: string
  granularity_family?: string
  resource_id?: string
  batch_id?: string
  final_status?: string
  region_candidate_id?: string
  circuit_id?: string
  projection_id?: string
  include_inactive?: boolean
  limit?: number
  offset?: number
}) => {
  const q: Record<string, string | number | boolean | null | undefined> = {}
  if (p?.query) q.query = p.query
  if (p?.target_types?.length) q.target_types = p.target_types.join(',')
  if (p?.source_atlas) q.source_atlas = p.source_atlas
  if (p?.granularity_level) q.granularity_level = p.granularity_level
  if (p?.granularity_family) q.granularity_family = p.granularity_family
  if (p?.resource_id) q.resource_id = p.resource_id
  if (p?.batch_id) q.batch_id = p.batch_id
  if (p?.final_status) q.final_status = p.final_status
  if (p?.region_candidate_id) q.region_candidate_id = p.region_candidate_id
  if (p?.circuit_id) q.circuit_id = p.circuit_id
  if (p?.projection_id) q.projection_id = p.projection_id
  if (p?.include_inactive != null) q.include_inactive = p.include_inactive
  if (p?.limit != null) q.limit = p.limit
  if (p?.offset != null) q.offset = p.offset
  return getJson<FinalBrowserSearchResponse>('/api/final-macro-clinical/browser/search', q)
}

export const getFinalRegionNeighborhood = (regionCandidateId: string, _p?: Record<string, unknown>) =>
  getJson<FinalRegionNeighborhoodResponse>(`/api/final-macro-clinical/browser/region/${regionCandidateId}`)

export const getFinalCircuitDetail = (finalCircuitId: string) =>
  getJson<FinalCircuitDetailResponse>(`/api/final-macro-clinical/browser/circuit/${finalCircuitId}`)

export const getFinalProjectionDetail = (finalProjectionId: string) =>
  getJson<FinalProjectionDetailResponse>(`/api/final-macro-clinical/browser/projection/${finalProjectionId}`)

export const getFinalObjectDetail = (targetType: string, finalId: string) =>
  getJson<FinalObjectDetailResponse>(`/api/final-macro-clinical/browser/object/${targetType}/${finalId}`)

export const getFinalGraph = (p: {
  center_type: string
  center_id: string
  depth?: number
  source_atlas?: string
  granularity_level?: string
  include_functions?: boolean
  include_evidence?: boolean
  include_triples?: boolean
  limit?: number
}) => getJson<FinalGraphResponse>('/api/final-macro-clinical/browser/graph', p)

// ── Final KG Export (Step 8.17) ─────────────────────────────────────────────
export type FinalKgExportFormat = 'jsonl' | 'csv' | 'neo4j_csv'

export type FinalKgExportTargetType =
  | 'brain_region'
  | 'region_function'
  | 'circuit'
  | 'circuit_step'
  | 'circuit_function'
  | 'projection'
  | 'projection_function'
  | 'circuit_projection_membership'
  | 'triple'
  | 'evidence'

export interface FinalKgExportScope {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  source_version?: string
  granularity_level?: string
  granularity_family?: string
  final_status?: string
  include_inactive?: boolean
}

export interface FinalKgExportRequest {
  target_types?: FinalKgExportTargetType[]
  formats?: FinalKgExportFormat[]
  scope?: FinalKgExportScope
  dry_run?: boolean
  include_evidence?: boolean
  include_provenance?: boolean
  include_triples?: boolean
  include_readme?: boolean
  max_nodes?: number
  max_edges?: number
  export_label?: string
}

export interface FinalKgExportPreviewResponse {
  dry_run: boolean
  candidate_counts: Record<string, number>
  estimated_node_count: number
  estimated_edge_count: number
  estimated_file_count: number
  warnings: string[]
  sample_nodes: Record<string, unknown>[]
  sample_edges: Record<string, unknown>[]
}

export interface FinalKgExportManifestCounts {
  nodes: number
  edges: number
  evidence: number
  provenance: number
}

export interface FinalKgExportManifest {
  export_id: string
  created_at: string
  created_by?: string
  export_label?: string | null
  scope: Record<string, unknown>
  formats: string[]
  target_types: string[]
  counts: FinalKgExportManifestCounts
  files: Record<string, string>
  schema_version: string
  app_version: string
  warnings: string[]
  boundaries: Record<string, boolean>
}

export interface FinalKgExportRunResponse {
  dry_run: boolean
  export_id?: string | null
  export_dir?: string | null
  manifest?: FinalKgExportManifest | null
  files: string[]
  counts: FinalKgExportManifestCounts
  warnings: string[]
}

export interface FinalKgExportManifestRead {
  export_id: string
  created_at: string
  scope: Record<string, unknown>
  formats: string[]
  target_types: string[]
  counts: FinalKgExportManifestCounts
  files: Record<string, string>
  warnings: string[]
  export_label?: string | null
}

export interface FinalKgExportFileRead {
  export_id: string
  filename: string
  size_bytes: number
  modified_at: string
  download_url: string
}

export const runFinalKgExport = (payload: FinalKgExportRequest) =>
  postJson<FinalKgExportRunResponse | FinalKgExportPreviewResponse>('/api/final-macro-clinical/export/run', payload)

export const listFinalKgExports = () =>
  getJson<{ items: FinalKgExportManifestRead[]; total: number }>('/api/final-macro-clinical/export/list')

export const getFinalKgExportManifest = (exportId: string) =>
  getJson<FinalKgExportManifest>(`/api/final-macro-clinical/export/${exportId}/manifest`)

export const listFinalKgExportFiles = (exportId: string) =>
  getJson<{ export_id: string; files: FinalKgExportFileRead[] }>(`/api/final-macro-clinical/export/${exportId}/files`)

export const getFinalKgExportFileUrl = (exportId: string, filename: string) =>
  buildApiUrl(`/api/final-macro-clinical/export/${exportId}/files/${filename}`)

export interface MirrorPromotionScope {
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  source_version?: string
  granularity_level?: string
  granularity_family?: string
  mirror_status?: string[]
  review_status?: string[]
  promotion_status?: string[]
}

export interface MirrorPromotionRequest {
  target_types: Array<'connection' | 'function' | 'circuit' | 'triple'>
  scope?: MirrorPromotionScope
  connection_ids?: string[]
  function_ids?: string[]
  circuit_ids?: string[]
  triple_ids?: string[]
  dry_run?: boolean
  operator?: string
  reason?: string
  confirmation_text?: string
  limit?: number
}

export interface MirrorPromotionPreviewItem {
  target_type: string
  mirror_target_id: string
  display_label: string
  eligible: boolean
  ineligible_reason?: string | null
  final_target_type?: string | null
  planned_action?: string | null
  duplicate?: boolean
  confidence?: number | null
  review_record_id?: string | null
  validation_summary?: Record<string, unknown>
}

export interface MirrorPromotionResponse {
  run_id?: string | null
  dry_run: boolean
  required_confirmation?: string | null
  object_count: number
  eligible_count: number
  promoted_count: number
  skipped_duplicate_count: number
  skipped_ineligible_count: number
  failed_count: number
  preview_items?: MirrorPromotionPreviewItem[]
  promotion_record_ids?: string[]
  final_object_ids?: Record<string, string[]>
  warnings?: string[]
}

export interface MirrorPromotionRun {
  id: string
  target_types: string[]
  scope_json: Record<string, unknown>
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  source_version?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  status: string
  object_count: number
  eligible_count: number
  promoted_count: number
  skipped_duplicate_count: number
  skipped_ineligible_count: number
  failed_count: number
  dry_run: boolean
  confirmation_text?: string | null
  required_confirmation?: string | null
  operator?: string | null
  reason?: string | null
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
}

export interface MirrorPromotionRecord {
  id: string
  run_id: string
  target_type: string
  mirror_target_id: string
  final_target_type?: string | null
  final_target_id?: string | null
  review_record_id?: string | null
  status: string
  message?: string | null
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  created_at: string
}

export interface FinalRegionConnection {
  id: string
  source_mirror_connection_id?: string | null
  connection_type: string
  directionality: string
  source_atlas: string
  granularity_level: string
  final_status: string
  created_at: string
}

export interface FinalRegionFunction {
  id: string
  source_mirror_function_id?: string | null
  function_term: string
  source_atlas: string
  granularity_level: string
  final_status: string
  created_at: string
}

export interface FinalRegionCircuit {
  id: string
  source_mirror_circuit_id?: string | null
  circuit_name: string
  source_atlas: string
  granularity_level: string
  final_status: string
  created_at: string
}

export interface FinalKgTriple {
  id: string
  source_mirror_triple_id?: string | null
  subject_label: string
  predicate: string
  object_label: string
  source_atlas: string
  granularity_level: string
  final_status: string
  created_at: string
}

export const previewMirrorPromotion = (payload: MirrorPromotionRequest) =>
  postJson<MirrorPromotionResponse>('/api/mirror-kg/promotion/preview', { ...payload, dry_run: true })

export const runMirrorPromotion = (payload: MirrorPromotionRequest) =>
  postJson<MirrorPromotionResponse>('/api/mirror-kg/promotion/run', { ...payload, dry_run: false })

export const listMirrorPromotionRuns = (p?: {
  target_type?: string
  status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorPromotionRun>>('/api/mirror-kg/promotion/runs', p)

export const getMirrorPromotionRun = (runId: string) =>
  getJson<MirrorPromotionRun & { records_summary?: Record<string, number> }>(
    `/api/mirror-kg/promotion/runs/${runId}`,
  )

export const listMirrorPromotionRecords = (p?: {
  run_id?: string
  target_type?: string
  mirror_target_id?: string
  status?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorPromotionRecord>>('/api/mirror-kg/promotion/records', p)

export const listFinalConnections = (p?: Record<string, string | number | undefined>) =>
  getJson<Paginated<FinalRegionConnection>>('/api/final-kg/connections', p)

export const listFinalFunctions = (p?: Record<string, string | number | undefined>) =>
  getJson<Paginated<FinalRegionFunction>>('/api/final-kg/functions', p)

export const listFinalCircuits = (p?: Record<string, string | number | undefined>) =>
  getJson<Paginated<FinalRegionCircuit>>('/api/final-kg/circuits', p)

export const listFinalTriples = (p?: Record<string, string | number | undefined>) =>
  getJson<Paginated<FinalKgTriple>>('/api/final-kg/triples', p)

export const listMirrorEvidence = (p?: {
  evidence_target_type?: string
  evidence_target_id?: string
  llm_run_id?: string
  limit?: number
  offset?: number
}) => getJson<Paginated<MirrorEvidenceRecord>>('/api/mirror-kg/evidence', p)

export const getMirrorEvidence = (id: string) =>
  getJson<MirrorEvidenceRecord>(`/api/mirror-kg/evidence/${id}`)

export const createMirrorEvidence = (body: Partial<MirrorEvidenceRecord>) =>
  postJson<MirrorEvidenceRecord>('/api/mirror-kg/evidence', body)

export interface SameGranularityConnectionExtractionRequest {
  provider: string
  model_name?: string | null
  candidate_ids: string[]
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    granularity_level?: string
    granularity_family?: string
  }
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_candidate_pairs?: number
  pair_strategy?: 'all_pairs' | 'region_centered'
  center_candidate_id?: string
  allowed_connection_types?: string[]
  create_mirror_records?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface SameGranularityConnectionExtractionResponse {
  run_id?: string | null
  item_id?: string | null
  task_type: string
  provider?: string | null
  model_name?: string | null
  status?: string | null
  candidate_count: number
  pair_count: number
  connection_count?: number
  mirror_connection_created_count?: number
  mirror_connection_skipped_duplicate_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string | null
  user_prompt?: string | null
  warnings?: string[]
}

export const runSameGranularityConnectionExtraction = (
  payload: SameGranularityConnectionExtractionRequest,
) =>
  postJson<SameGranularityConnectionExtractionResponse>(
    '/api/llm-extraction/same-granularity-connections',
    payload,
  )

// ── Composite LLM Extraction Workflows ────────────────────────────────────────

export type CompositeWorkflowType =
  | 'connection_with_function'
  | 'circuit_with_function_steps'
  | 'triple_generation'

export type CompositeWorkflowStatus =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'cancelled'
  | 'cleanup_in_progress'
  | 'cleanup_done'
  | 'cleanup_failed'
  | 'succeeded'
  | 'partially_succeeded'
  | 'no_edges'
  | 'succeeded_no_edges'
  | 'failed'
  | 'failed_provider_not_called'
  | 'failed_provider_empty_response'
  | 'failed_parse_error'
  | 'failed_no_output'
  | 'dry_run'

export type CompositeStepStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'skipped'
  | 'skipped_no_projection'
  | 'skipped_dependency_failed'
  | 'cancelled'
  | 'failed'

export interface CompositeWorkflowCancelRequest {
  cleanup?: boolean
  reason?: string
}

export interface CompositeWorkflowCancelResponse {
  workflow_run_id: string
  status: CompositeWorkflowStatus
  cleanup: boolean
  deleted: Record<string, number>
  warnings?: string[]
  errors?: string[]
}

export interface CompositeWorkflowRunRequest {
  workflow_type: CompositeWorkflowType
  provider: string
  model_name?: string | null
  dry_run?: boolean
  candidate_ids?: string[]
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  source_version?: string
  granularity_level?: string
  granularity_family?: string
  create_mirror_records?: boolean
  create_triples?: boolean
  create_evidence?: boolean
  include_region_context?: boolean
  include_existing_context?: boolean
  explicit_batching_enabled?: boolean
  batch_strategy?: string | null
  batch_size?: number | null
  notes?: string | null
  debug_single_pack?: boolean
  debug_max_packs?: number | null
  temperature?: number
  max_tokens?: number
  prompt_template_key?: string
  prompt_overrides?: Record<string, string>
}

export interface CompositeWorkflowStepRead {
  id: string
  workflow_run_id: string
  step_order: number
  step_key: string
  step_label?: string | null
  status: CompositeStepStatus
  llm_run_id?: string | null
  llm_item_id?: string | null
  created_counts?: Record<string, number>
  warnings?: string[]
  errors?: string[]
  execution_summary?: Record<string, unknown>
  started_at?: string | null
  completed_at?: string | null
}

export interface CompositeWorkflowCreatedTarget {
  target_type: string
  target_table?: string | null
  ids?: string[]
  count?: number
  step_key?: string | null
}

export interface LlmWorkflowEvent {
  event_id?: string
  ts: string
  level: 'info' | 'warning' | 'error'
  step_key?: string | null
  event: string
  message: string
  data?: Record<string, unknown>
}

export interface CompositeWorkflowRunResponse {
  workflow_run_id: string
  workflow_type: CompositeWorkflowType
  status: CompositeWorkflowStatus
  dry_run: boolean
  candidate_count: number
  pair_count: number
  steps: CompositeWorkflowStepRead[]
  progress_percent?: number
  result_summary?: Record<string, unknown>
  created_targets?: CompositeWorkflowCreatedTarget[]
  warnings?: string[]
  errors?: string[]
  started_at?: string | null
  created_at?: string | null
  completed_at?: string | null
  recent_events?: LlmWorkflowEvent[]
  outcome?: string | null
  display_status?: string | null
  semantic_status?: string | null
}

export interface CompositeWorkflowStartResponse {
  workflow_run_id: string
  workflow_type: CompositeWorkflowType
  status: CompositeWorkflowStatus
  dry_run: boolean
  candidate_count: number
  pair_count: number
  steps: CompositeWorkflowStepRead[]
  progress_percent?: number
  warnings?: string[]
  recent_events?: LlmWorkflowEvent[]
}

export interface CompositeWorkflowRunRead {
  id: string
  workflow_type: CompositeWorkflowType
  status: CompositeWorkflowStatus
  provider?: string | null
  model_name?: string | null
  dry_run: boolean
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  source_version?: string | null
  granularity_level?: string | null
  granularity_family?: string | null
  candidate_count: number
  pair_count: number
  progress_percent?: number
  result_summary?: Record<string, unknown>
  provider_audit?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown>>
  warnings?: string[]
  errors?: string[]
  started_at?: string | null
  completed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  steps?: CompositeWorkflowStepRead[]
  recent_events?: LlmWorkflowEvent[]
  outcome?: string | null
  display_status?: string | null
  semantic_status?: string | null
}

export interface CompositeWorkflowRunListResponse {
  items: CompositeWorkflowRunRead[]
  total: number
  limit: number
  offset: number
}

export interface CompositeWorkflowStepListResponse {
  items: CompositeWorkflowStepRead[]
  total: number
}

export function normalizeCompositeWorkflowPayload(
  payload: CompositeWorkflowRunRequest,
): CompositeWorkflowRunRequest {
  return omitUndefined({
    ...payload,
    debug_single_pack: payload.debug_single_pack ?? false,
    debug_max_packs: payload.debug_max_packs ?? null,
    resource_id: normalizeOptionalUuid(payload.resource_id),
    batch_id: normalizeOptionalUuid(payload.batch_id),
    candidate_ids: filterNonEmptyIds(payload.candidate_ids),
    source_atlas: normalizeOptionalString(payload.source_atlas),
    source_version: normalizeOptionalString(payload.source_version),
    granularity_level: normalizeOptionalString(payload.granularity_level),
    granularity_family: normalizeOptionalString(payload.granularity_family),
    batch_strategy: normalizeOptionalString(payload.batch_strategy),
    notes: normalizeOptionalString(payload.notes),
    model_name: normalizeOptionalString(payload.model_name),
  }) as CompositeWorkflowRunRequest
}

export const runCompositeWorkflow = (payload: CompositeWorkflowRunRequest) =>
  postJson<CompositeWorkflowRunResponse>(
    '/api/llm-extraction/composite-workflows/run',
    normalizeCompositeWorkflowPayload(payload),
  )

export const startCompositeWorkflow = (payload: CompositeWorkflowRunRequest) =>
  postJson<CompositeWorkflowStartResponse>(
    '/api/llm-extraction/composite-workflows/start',
    normalizeCompositeWorkflowPayload(payload),
  )

export const listCompositeWorkflowRuns = (params?: {
  workflow_type?: string
  status?: string
  provider?: string
  batch_id?: string
  resource_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) => getJson<CompositeWorkflowRunListResponse>('/api/llm-extraction/composite-workflows/runs', params)

export const getCompositeWorkflowRun = (workflowRunId: string) =>
  getJson<CompositeWorkflowRunRead>(`/api/llm-extraction/composite-workflows/runs/${workflowRunId}`)

export const listCompositeWorkflowSteps = (workflowRunId: string) =>
  getJson<CompositeWorkflowStepListResponse>(
    `/api/llm-extraction/composite-workflows/runs/${workflowRunId}/steps`,
  )

export const cancelCompositeWorkflow = (
  workflowRunId: string,
  payload: CompositeWorkflowCancelRequest = { cleanup: true, reason: 'user_closed_modal' },
) =>
  postJson<CompositeWorkflowCancelResponse>(
    `/api/llm-extraction/composite-workflows/${workflowRunId}/cancel`,
    payload,
  )

export const pauseCompositeWorkflow = (workflowRunId: string) =>
  postJson<CompositeWorkflowCancelResponse>(
    `/api/llm-extraction/composite-workflows/${workflowRunId}/pause`,
    {},
  )

export const resumeCompositeWorkflow = (workflowRunId: string) =>
  postJson<CompositeWorkflowCancelResponse>(
    `/api/llm-extraction/composite-workflows/${workflowRunId}/resume`,
    {},
  )

export const retryFailedCompositeWorkflow = (workflowRunId: string) =>
  postJson<CompositeWorkflowStartResponse>(
    `/api/llm-extraction/composite-workflows/${workflowRunId}/retry-failed`,
    {},
  )

export interface SameGranularityFunctionExtractionRequest {
  provider: string
  model_name?: string | null
  candidate_ids: string[]
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    granularity_level?: string
    granularity_family?: string
  }
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_functions_per_region?: number
  allowed_function_categories?: string[]
  allowed_relation_types?: string[]
  create_mirror_records?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface SameGranularityFunctionExtractionResponse {
  run_id?: string | null
  item_id?: string | null
  task_type: string
  provider?: string | null
  model_name?: string | null
  status?: string | null
  candidate_count: number
  function_count?: number
  mirror_function_created_count?: number
  mirror_function_skipped_duplicate_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string | null
  user_prompt?: string | null
  warnings?: string[]
}

export const runSameGranularityFunctionExtraction = (
  payload: SameGranularityFunctionExtractionRequest,
) =>
  postJson<SameGranularityFunctionExtractionResponse>(
    '/api/llm-extraction/same-granularity-functions',
    payload,
  )

export interface SameGranularityCircuitExtractionRequest {
  provider: string
  model_name?: string | null
  candidate_ids: string[]
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    granularity_level?: string
    granularity_family?: string
  }
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_circuits?: number
  min_regions_per_circuit?: number
  max_regions_per_circuit?: number
  include_connection_context?: boolean
  include_function_context?: boolean
  connection_ids?: string[]
  function_ids?: string[]
  allowed_circuit_types?: string[]
  create_mirror_records?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface SameGranularityCircuitExtractionResponse {
  run_id?: string | null
  item_id?: string | null
  task_type: string
  provider?: string | null
  model_name?: string | null
  status?: string | null
  candidate_count: number
  connection_context_count?: number
  function_context_count?: number
  circuit_count?: number
  mirror_circuit_created_count?: number
  mirror_circuit_skipped_duplicate_count?: number
  circuit_region_created_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string | null
  user_prompt?: string | null
  warnings?: string[]
}

export const runSameGranularityCircuitExtraction = (
  payload: SameGranularityCircuitExtractionRequest,
) =>
  postJson<SameGranularityCircuitExtractionResponse>(
    '/api/llm-extraction/same-granularity-circuits',
    payload,
  )

export interface CircuitToStepsExtractionRequest {
  provider: string
  model_name?: string
  circuit_id: string
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_steps?: number
  include_circuit_regions?: boolean
  create_mirror_records?: boolean
}

export interface CircuitToStepsExtractionResponse {
  run_id?: string
  item_id?: string
  task_type: string
  provider?: string
  model_name?: string
  status?: string
  circuit_id: string
  input_region_count?: number
  step_count?: number
  mirror_step_created_count?: number
  mirror_step_skipped_duplicate_count?: number
  dry_run: boolean
  system_prompt?: string
  user_prompt?: string
  warnings?: string[]
}

export const runCircuitToStepsExtraction = (
  payload: CircuitToStepsExtractionRequest,
) =>
  postJson<CircuitToStepsExtractionResponse>(
    '/api/llm-extraction/circuit-to-steps',
    payload,
  )

export interface CircuitToFunctionsExtractionRequest {
  circuit_ids?: string[]
  batch_id?: string
  resource_id?: string
  provider?: string
  model_name?: string
  dry_run?: boolean
  overwrite_policy?: string
  include_related_steps?: boolean
  include_provenance?: boolean
  prompt_template_key?: string
  prompt_overrides?: Record<string, string>
  temperature?: number
  max_tokens?: number
  limit?: number
}

export interface CircuitFunctionCreatedTarget {
  target_type: string
  target_table: string
  ids: string[]
  count: number
}

export interface CircuitToFunctionsExtractionResponse {
  status: string
  target_type: string
  source_target_type: string
  circuit_count: number
  created_count: number
  updated_count: number
  skipped_count: number
  failed_count: number
  created_ids: string[]
  updated_ids: string[]
  skipped: Array<{ circuit_id?: string; reason?: string }>
  errors: Array<{ circuit_id?: string; message?: string }>
  warnings?: string[]
  prompt_preview?: Record<string, unknown>
  estimated_model_calls?: number
  estimated_input_tokens?: number
  dry_run: boolean
  created_targets?: CircuitFunctionCreatedTarget[]
}

export const runCircuitToFunctionsExtraction = (
  payload: CircuitToFunctionsExtractionRequest,
) =>
  postJson<CircuitToFunctionsExtractionResponse>(
    '/api/llm-extraction/circuit-to-functions',
    payload,
  )

export interface CircuitStepsToProjectionsExtractionRequest {
  provider: string
  model_name?: string
  circuit_id: string
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_projections?: number
  step_ids?: string[]
  include_existing_projections?: boolean
  create_mirror_records?: boolean
  create_memberships?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface CircuitStepsToProjectionsExtractionResponse {
  run_id?: string
  item_id?: string
  task_type: string
  provider?: string
  model_name?: string
  status?: string
  circuit_id: string
  input_step_count?: number
  existing_projection_context_count?: number
  projection_count?: number
  mirror_projection_created_count?: number
  mirror_projection_skipped_duplicate_count?: number
  membership_created_count?: number
  membership_skipped_duplicate_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string
  user_prompt?: string
  warnings?: string[]
}

export const runCircuitStepsToProjectionsExtraction = (
  payload: CircuitStepsToProjectionsExtractionRequest,
) =>
  postJson<CircuitStepsToProjectionsExtractionResponse>(
    '/api/llm-extraction/circuit-steps-to-projections',
    payload,
  )

export interface ProjectionToFunctionsExtractionRequest {
  provider: string
  model_name?: string
  projection_ids: string[]
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_functions_per_projection?: number
  include_circuit_context?: boolean
  include_region_context?: boolean
  create_mirror_records?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface ProjectionToFunctionsExtractionResponse {
  run_id?: string
  item_id?: string
  task_type: string
  provider?: string
  model_name?: string
  status?: string
  projection_count: number
  circuit_context_count?: number
  function_count?: number
  mirror_projection_function_created_count?: number
  mirror_projection_function_skipped_duplicate_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string
  user_prompt?: string
  warnings?: string[]
}

export const runProjectionToFunctionsExtraction = (
  payload: ProjectionToFunctionsExtractionRequest,
) =>
  postJson<ProjectionToFunctionsExtractionResponse>(
    '/api/llm-extraction/projection-to-functions',
    payload,
  )

export interface ProjectionsToCircuitsExtractionRequest {
  provider: string
  model_name?: string
  projection_ids: string[]
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_circuits?: number
  max_steps_per_circuit?: number
  include_existing_circuits?: boolean
  reuse_existing_circuits?: boolean
  create_mirror_circuits?: boolean
  create_circuit_steps?: boolean
  create_memberships?: boolean
  create_triples?: boolean
  create_evidence?: boolean
}

export interface ProjectionsToCircuitsExtractionResponse {
  run_id?: string
  item_id?: string
  task_type: string
  provider?: string
  model_name?: string
  status?: string
  projection_count: number
  existing_circuit_context_count?: number
  inferred_circuit_count?: number
  mirror_circuit_created_count?: number
  mirror_circuit_reused_count?: number
  mirror_circuit_skipped_duplicate_count?: number
  circuit_step_created_count?: number
  circuit_step_skipped_duplicate_count?: number
  membership_created_count?: number
  membership_skipped_duplicate_count?: number
  triple_created_count?: number
  evidence_created_count?: number
  dry_run: boolean
  system_prompt?: string
  user_prompt?: string
  warnings?: string[]
}

export const runProjectionsToCircuitsExtraction = (
  payload: ProjectionsToCircuitsExtractionRequest,
) =>
  postJson<ProjectionsToCircuitsExtractionResponse>(
    '/api/llm-extraction/projections-to-circuits',
    payload,
  )

// ── Circuit-Projection Cross Validation (Step 8.11) ───────────────────────────

export interface CircuitProjectionCrossValidationRequest {
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    source_version?: string
    granularity_level?: string
    granularity_family?: string
    circuit_ids?: string[]
    projection_ids?: string[]
    membership_ids?: string[]
    include_unverified?: boolean
    include_conflicts?: boolean
  }
  dry_run?: boolean
  apply_updates?: boolean
  update_bidirectional?: boolean
  update_conflicts?: boolean
  limit?: number
}

export interface CircuitProjectionCrossValidationResultPreview {
  circuit_id: string
  projection_id: string
  circuit_to_projection_membership_id?: string | null
  projection_to_circuit_membership_id?: string | null
  validation_status: string
  support_level: string
  agreement_score?: number | null
  source_step_agreement?: boolean | null
  target_step_agreement?: boolean | null
  direction_agreement?: boolean | null
  scope_agreement?: boolean | null
  conflict_reason?: string | null
  details_json?: Record<string, unknown>
}

export interface CircuitProjectionCrossValidationResponse {
  run_id?: string | null
  dry_run: boolean
  apply_updates: boolean
  membership_count: number
  circuit_supported_count: number
  projection_supported_count: number
  bidirectionally_supported_count: number
  conflict_count: number
  insufficient_evidence_count: number
  updated_membership_count: number
  results_preview?: CircuitProjectionCrossValidationResultPreview[]
  warnings?: string[]
}

export interface MirrorCircuitProjectionCrossValidationRun {
  id: string
  scope_json: Record<string, unknown>
  resource_id?: string | null
  batch_id?: string | null
  source_atlas?: string | null
  granularity_level?: string | null
  status: string
  membership_count: number
  circuit_supported_count: number
  projection_supported_count: number
  bidirectionally_supported_count: number
  conflict_count: number
  insufficient_evidence_count: number
  updated_membership_count: number
  dry_run: boolean
  apply_updates: boolean
  created_at: string
}

export interface MirrorCircuitProjectionCrossValidationResult {
  id: string
  run_id: string
  circuit_id: string
  projection_id: string
  circuit_to_projection_membership_id?: string | null
  projection_to_circuit_membership_id?: string | null
  validation_status: string
  support_level: string
  agreement_score?: number | null
  source_step_agreement?: boolean | null
  target_step_agreement?: boolean | null
  direction_agreement?: boolean | null
  scope_agreement?: boolean | null
  conflict_reason?: string | null
  details_json?: Record<string, unknown>
  created_at: string
}

export const runCircuitProjectionCrossValidation = (
  payload: CircuitProjectionCrossValidationRequest,
) =>
  postJson<CircuitProjectionCrossValidationResponse>(
    '/api/mirror-kg/circuit-projection-cross-validation/run',
    payload,
  )

export const listCircuitProjectionCrossValidationRuns = (p?: {
  status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) =>
  getJson<Paginated<MirrorCircuitProjectionCrossValidationRun>>(
    '/api/mirror-kg/circuit-projection-cross-validation/runs',
    p,
  )

export const getCircuitProjectionCrossValidationRun = (runId: string) =>
  getJson<MirrorCircuitProjectionCrossValidationRun>(
    `/api/mirror-kg/circuit-projection-cross-validation/runs/${runId}`,
  )

export const listCircuitProjectionCrossValidationResults = (p?: {
  run_id?: string
  circuit_id?: string
  projection_id?: string
  validation_status?: string
  support_level?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) =>
  getJson<Paginated<MirrorCircuitProjectionCrossValidationResult>>(
    '/api/mirror-kg/circuit-projection-cross-validation/results',
    p,
  )

// ── Dual-Model Verification Execution (Step 8.12) ─────────────────────────────

export interface DualModelVerificationRequest {
  object_type: 'circuit' | 'projection' | 'circuit_projection_membership' | 'projection_function' | 'circuit_step' | 'triple'
  object_ids?: string[]
  scope?: {
    resource_id?: string
    batch_id?: string
    source_atlas?: string
    source_version?: string
    granularity_level?: string
    granularity_family?: string
  }
  model_a_provider?: string
  model_a_name?: string
  model_b_provider?: string
  model_b_name?: string
  prompt_template_key?: string
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
  max_objects?: number
  include_cross_validation_context?: boolean
  include_evidence_context?: boolean
  include_review_context?: boolean
  create_results?: boolean
}

export interface DualModelVerificationResultPreview {
  object_type: string
  object_id: string
  model_a_decision?: string | null
  model_a_confidence?: number | null
  model_b_decision?: string | null
  model_b_confidence?: number | null
  consensus_status: string
  consensus_score?: number | null
  conflict_summary?: string | null
  recommended_review_priority: string
  evidence_text?: string | null
  uncertainty_reason?: string | null
}

export interface DualModelVerificationResponse {
  run_id?: string | null
  object_type: string
  object_count: number
  model_a_provider?: string
  model_a_run_id?: string | null
  model_b_provider?: string
  model_b_run_id?: string | null
  consensus_supported_count?: number
  consensus_rejected_count?: number
  model_conflict_count?: number
  insufficient_information_count?: number
  needs_human_review_count?: number
  result_count?: number
  dry_run: boolean
  model_a_system_prompt?: string
  model_a_user_prompt?: string
  model_b_system_prompt?: string
  model_b_user_prompt?: string
  results_preview?: DualModelVerificationResultPreview[]
  warnings?: string[]
}

export const runDualModelVerification = (payload: DualModelVerificationRequest) =>
  postJson<DualModelVerificationResponse>('/api/mirror-kg/dual-model-verification/run', payload)

export const listDualModelVerificationExecutionRuns = (p?: {
  verification_task_type?: string
  status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) =>
  getJson<Paginated<MirrorDualModelVerificationRun>>('/api/mirror-kg/dual-model-verification/runs', p)

export const getDualModelVerificationExecutionRun = (runId: string) =>
  getJson<MirrorDualModelVerificationRun>(`/api/mirror-kg/dual-model-verification/runs/${runId}`)

export const listDualModelVerificationExecutionResults = (p?: {
  run_id?: string
  object_type?: string
  object_id?: string
  consensus_status?: string
  resource_id?: string
  batch_id?: string
  source_atlas?: string
  granularity_level?: string
  limit?: number
  offset?: number
}) =>
  getJson<Paginated<MirrorDualModelVerificationResult>>('/api/mirror-kg/dual-model-verification/results', p)

// ── Workbench Pipeline Overview (read-only aggregation) ───────────────────────
export interface PipelineAction {
  action: string
  label: string
  enabled: boolean
  reason: string | null
}

export interface BoundFilePipelineRead {
  id: string
  file_id: string
  file_role_in_batch: string
  sort_order: number
  created_at: string
  original_filename: string | null
  file_type: string | null
  file_role: string | null
  file_status: string | null
  is_active: boolean
  can_parse: boolean
  inactive_reason: string | null
  intermediate_status: string | null
  latest_intermediate_artifact_id: string | null
  latest_intermediate_kind: string | null
  latest_intermediate_schema: string | null
  parser_compatible_for_aal3_xml: boolean
  parser_incompatible_reason: string | null
  warning: string | null
}

/** @deprecated Use BoundFilePipelineRead in pipeline overview */
export interface ImportBatchFileBinding {
  id: string
  file_id: string
  file_role_in_batch: string
  sort_order: number
  created_at: string
}

export interface ImportBatchEvent {
  id: string
  batch_id: string
  event_type: string
  from_status: string | null
  to_status: string | null
  message: string | null
  payload_json?: Record<string, unknown> | null
  created_at: string
}

export interface RawParseRun {
  id: string
  batch_id: string
  resource_id: string
  parser_key: string
  parser_version: string
  status: string
  output_count: number
  warning_count: number
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface CandidateGenerationRun {
  id: string
  batch_id: string
  resource_id: string
  parse_run_id: string
  generator_key: string
  generator_version: string
  status: string
  output_count: number
  skipped_count: number
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface LatestValidationSummary {
  passed_count: number
  failed_count: number
  warning_count: number
}

export interface ImportBatchPipelineOverview {
  batch: ImportBatch
  bound_files: BoundFilePipelineRead[]
  events: ImportBatchEvent[]
  parse_runs: RawParseRun[]
  raw_label_count: number
  raw_labels_preview: RawAal3Label[]
  generation_runs: CandidateGenerationRun[]
  candidate_count: number
  candidate_status_counts: Record<string, number>
  candidates_preview: CandidateBrainRegion[]
  validation_runs: RuleValidationRun[]
  latest_validation_summary: LatestValidationSummary | null
  next_allowed_actions: PipelineAction[]
}

export const getImportBatchPipelineOverview = (batchId: string) =>
  getJson<ImportBatchPipelineOverview>(
    `/api/workbench/import-batches/${batchId}/overview`
  )

// ═══════════════════════════════════════════════════════════════════════════════
// SETTINGS — local Workbench runtime settings. API keys are never returned.
// ═══════════════════════════════════════════════════════════════════════════════

export interface SettingsOptions {
  languages: Array<{ value: 'zh-CN' | 'en-US'; label: string }>
  api_providers: Array<{ value: string; label: string; disabled?: boolean }>
  default_models: Record<string, string[]>
}

export interface PublicDeepSeekSettings {
  enabled: boolean
  base_url: string
  default_model: string
  api_key_configured: boolean
  api_key_masked: string | null
  timeout_seconds: number
  max_batch_size: number
}

export interface RuntimeSettings {
  api_providers: {
    deepseek: PublicDeepSeekSettings
  }
  basic: {
    default_page_size: number
    max_page_size: number
    show_debug_panels: boolean
  }
}

export interface RuntimeSettingsPatch {
  api_providers?: {
    deepseek?: {
      enabled?: boolean
      base_url?: string
      default_model?: string
      api_key?: string
      explicit_clear_api_key?: boolean
      timeout_seconds?: number
      max_batch_size?: number
    }
  }
  basic?: {
    default_page_size?: number
    max_page_size?: number
    show_debug_panels?: boolean
  }
}

export interface DeepSeekTestRequest {
  base_url?: string
  default_model?: string
  api_key?: string
}

export interface DeepSeekTestResponse {
  ok: boolean
  provider: 'deepseek'
  model: string | null
  latency_ms: number | null
  error_message: string | null
}

export const getSettingsOptions = () =>
  getJson<SettingsOptions>('/api/settings/options')

export const getRuntimeSettings = () =>
  getJson<RuntimeSettings>('/api/settings/runtime')

export const updateRuntimeSettings = (body: RuntimeSettingsPatch) =>
  patchJson<RuntimeSettings>('/api/settings/runtime', body)

export const testDeepSeekConnection = (body: DeepSeekTestRequest) =>
  postJson<DeepSeekTestResponse>('/api/settings/api-providers/deepseek/test', body)

// ═══════════════════════════════════════════════════════════════════════════════
// FILE NORMALIZATION — intermediate state for files
// ═══════════════════════════════════════════════════════════════════════════════

export interface IntermediateArtifact {
  id: string
  run_id: string
  resource_id: string
  file_id: string
  artifact_key: string
  artifact_kind: string
  schema_version: string
  source_format: string | null
  row_count: number | null
  content_jsonb: Record<string, unknown> | null
  preview_jsonb: Record<string, unknown> | null
  metadata_jsonb: Record<string, unknown> | null
  warnings_jsonb: string[] | null
  status: string
  created_at: string
  updated_at: string
}

export interface NormalizationRun {
  id: string
  run_code: string
  resource_id: string
  file_id: string
  file_sha256: string | null
  original_filename: string | null
  file_type: string | null
  file_role: string | null
  normalizer_key: string
  normalizer_version: string
  status: string
  artifact_count: number
  warning_count: number
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface FileNormalizeResponse {
  run_id: string
  run_code: string
  status: string
  artifact_count: number
  warning_count: number
  error_message: string | null
  artifacts: IntermediateArtifact[]
}

export interface FileIntermediateStatus {
  file_id: string
  status?: 'ready' | 'missing' | 'failed'
  has_active_intermediate: boolean
  latest_run_id: string | null
  latest_run_status: string | null
  latest_artifact_kind: string | null
  latest_artifact?: IntermediateArtifact | null
  latest_run_created_at: string | null
  latest_run_error?: string | null
  artifact_count: number
  artifacts?: IntermediateArtifact[]
  runs?: NormalizationRun[]
}

export interface IntermediatePreview {
  file_id: string
  artifact_id: string
  artifact_kind: string
  source_format: string | null
  row_count: number | null
  preview: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
}

export const normalizeFile = (fileId: string, force = false) =>
  postJson<FileNormalizeResponse>(`/api/files/${fileId}/normalize${force ? '?force=true' : ''}`, {})

export const getFileIntermediateStatus = (fileId: string) =>
  getJson<FileIntermediateStatus>(`/api/files/${fileId}/intermediate`)

export const getFileIntermediate = getFileIntermediateStatus

export const listNormalizationRuns = (fileId: string) =>
  getJson<NormalizationRun[]>(`/api/files/${fileId}/intermediate/runs`)

export const listFileIntermediateRuns = listNormalizationRuns

export const getIntermediatePreview = (fileId: string) =>
  getJson<IntermediatePreview>(`/api/files/${fileId}/intermediate/preview`)

// ═══════════════════════════════════════════════════════════════════════════════
// WORKSPACE FILES — public staging files without resource_id
// Workspace files CANNOT directly enter Import Batches.
// Use attachWorkspaceFileToResource first.
// ═══════════════════════════════════════════════════════════════════════════════

export interface WorkspaceFile {
  id: string
  workspace_file_code?: string | null
  original_filename: string
  safe_filename: string
  stored_filename: string
  storage_path: string
  file_ext: string
  mime_type?: string | null
  file_type: string
  file_role: string
  file_size_bytes: number
  sha256: string
  status: string
  description?: string | null
  remark?: string | null
  uploaded_by?: string | null
  source: string
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface WorkspaceFileListResponse {
  items: WorkspaceFile[]
  total: number
  limit: number
  offset: number
}

export interface WorkspaceFileUpdate {
  file_type?: string
  file_role?: string
  description?: string | null
  remark?: string | null
  status?: string
}

export interface WorkspaceFileQuery {
  status?: string
  file_type?: string
  file_role?: string
  limit?: number
  offset?: number
  include_archived?: boolean
}

export interface WorkspaceFileAttachRequest {
  resource_id: string
  file_type?: string
  file_role?: string
  description?: string
  remark?: string
}

export const uploadWorkspaceFile = (fd: FormData) =>
  uploadForm<WorkspaceFile>('/api/workspace-files', fd)

export const listWorkspaceFiles = (params?: WorkspaceFileQuery) => {
  const qs = new URLSearchParams()
  if (params?.status) qs.set('status', params.status)
  if (params?.file_type) qs.set('file_type', params.file_type)
  if (params?.file_role) qs.set('file_role', params.file_role)
  if (params?.limit !== undefined) qs.set('limit', String(params.limit))
  if (params?.offset !== undefined) qs.set('offset', String(params.offset))
  if (params?.include_archived) qs.set('include_archived', 'true')
  const q = qs.toString()
  return getJson<WorkspaceFileListResponse>(`/api/workspace-files${q ? `?${q}` : ''}`)
}

export const getWorkspaceFile = (id: string) =>
  getJson<WorkspaceFile>(`/api/workspace-files/${id}`)

export const updateWorkspaceFile = (id: string, body: WorkspaceFileUpdate) =>
  patchJson<WorkspaceFile>(`/api/workspace-files/${id}`, body)

export const archiveWorkspaceFile = (id: string) =>
  deleteJson<WorkspaceFile>(`/api/workspace-files/${id}`)

export const getWorkspaceFilePreview = (id: string) =>
  getJson<FilePreview>(`/api/workspace-files/${id}/preview`)

export const getWorkspaceFileDownloadUrl = (id: string) =>
  buildApiUrl(`/api/workspace-files/${id}/download`)

export const attachWorkspaceFileToResource = (id: string, body: WorkspaceFileAttachRequest) =>
  postJson<ResourceFile>(`/api/workspace-files/${id}/attach-to-resource`, body)
