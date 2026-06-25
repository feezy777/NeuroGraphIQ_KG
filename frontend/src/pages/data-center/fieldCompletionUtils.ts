import { ApiError } from '../../api/client'
import type {
  FieldCompletionScope,
  FieldCompletionTargetType,
  FieldCompletionItem,
  FieldCompletionUpdateSummary,
  UniversalFieldCompletionRequest,
  UniversalFieldCompletionResponse,
} from '../../api/endpoints'
import {
  type FormalFieldMapping,
  type FormalObjectType,
  computeMissingFields,
  getFieldValue,
  isFieldValueEmpty,
  isPresentFieldValue,
  isValueFromOverlay,
} from './formalFieldMappings'

export type FormalRow = Record<string, unknown> & { id: string }

export type OverlayPatch = Record<string, Record<string, unknown>>

export {
  getFieldValue,
  isFieldValueEmpty,
  isPresentFieldValue,
  isValueFromOverlay,
  computeMissingFields,
} from './formalFieldMappings'

/** Explicit mapping — FormalObjectType equals API target_type for all supported types. */
export function toApiTargetType(targetType: FormalObjectType): FieldCompletionTargetType {
  return targetType as FieldCompletionTargetType
}

export function getEnrichableColumns(mapping: FormalFieldMapping) {
  return mapping.columns.filter(c => c.enrichable)
}

/**
 * Returns the real formal field names (finalField) for all enrichable columns.
 * These are the names that should be sent to the backend as selected_fields.
 * Step 10.4.2: always use formal field names, never mirror field names.
 */
export function getEnrichableFormalFields(mapping: FormalFieldMapping): string[] {
  return mapping.columns
    .filter(c => c.enrichable && c.group !== 'governance')
    .map(c => c.finalField)
}

/**
 * Validates that all selected fields are enrichable formal field names from the mapping.
 * Returns { validFields, invalidFields } for frontend error display.
 */
export function validateSelectedFormalFields(
  selectedFields: string[],
  mapping: FormalFieldMapping,
): { validFields: string[]; invalidFields: string[] } {
  const enrichableSet = new Set(getEnrichableFormalFields(mapping))
  const validFields: string[] = []
  const invalidFields: string[] = []
  for (const f of selectedFields) {
    if (enrichableSet.has(f)) {
      validFields.push(f)
    } else {
      invalidFields.push(f)
    }
  }
  return { validFields, invalidFields }
}

export function countTotalMissing(objects: FormalRow[], mapping: FormalFieldMapping): number {
  return objects.reduce((sum, obj) => sum + computeMissingFields(obj, mapping).length, 0)
}

export function getCompletableFieldKeys(
  obj: FormalRow,
  mapping: FormalFieldMapping,
  fieldScope: FieldCompletionScope,
  selectedFieldKeys: string[],
): string[] {
  const enrichable = getEnrichableColumns(mapping).map(c => c.key)
  if (fieldScope === 'all_enrichable_fields') return enrichable
  if (fieldScope === 'selected_fields') {
    return selectedFieldKeys.filter(k => enrichable.includes(k))
  }
  return enrichable.filter(k => {
    const col = mapping.columns.find(c => c.key === k)
    const val = col ? getFieldValue(obj, col) : obj[k]
    return isFieldValueEmpty(val)
  })
}

export function hasCompletableFields(
  objects: FormalRow[],
  mapping: FormalFieldMapping,
  fieldScope: FieldCompletionScope,
  selectedFieldKeys: string[],
): boolean {
  if (objects.length === 0) return false
  return objects.some(obj =>
    getCompletableFieldKeys(obj, mapping, fieldScope, selectedFieldKeys).length > 0,
  )
}

export interface FieldCompletionFormOptions {
  provider: string
  modelName: string
  fieldScope: FieldCompletionScope
  selectedFieldKeys: string[]
  dryRun: boolean
  createMirrorUpdates: boolean
  createEvidence: boolean
  overwritePolicy: 'fill_missing_only' | 'suggest_only' | 'overwrite_with_review'
  includeExistingEvidence: boolean
  includeRelatedObjects: boolean
  includeProvenance: boolean
  promptTemplateKey: string
  promptOverrides: Record<string, string>
  temperature: number
  maxTokens: number
}

export const DEFAULT_FIELD_COMPLETION_OPTIONS: FieldCompletionFormOptions = {
  provider: 'deepseek',
  modelName: 'deepseek-chat',
  fieldScope: 'missing_only',
  selectedFieldKeys: [],
  dryRun: true,
  createMirrorUpdates: true,
  createEvidence: false,
  overwritePolicy: 'fill_missing_only',
  includeExistingEvidence: true,
  includeRelatedObjects: true,
  includeProvenance: true,
  promptTemplateKey: 'universal_field_completion_v1',
  promptOverrides: {},
  temperature: 0.2,
  maxTokens: 4000,
}

export function buildFieldCompletionRequest(
  mapping: FormalFieldMapping,
  selectedIds: string[],
  options: FieldCompletionFormOptions,
): UniversalFieldCompletionRequest {
  const selectedFields =
    options.fieldScope === 'selected_fields'
      ? options.selectedFieldKeys
      : []

  return {
    provider: options.provider,
    model_name: options.modelName || undefined,
    target_type: toApiTargetType(mapping.targetType),
    target_ids: selectedIds,
    field_scope: options.fieldScope,
    selected_fields: selectedFields,
    dry_run: options.dryRun,
    create_mirror_updates: options.createMirrorUpdates,
    create_evidence: options.createEvidence,
    overwrite_policy: options.overwritePolicy,
    include_existing_evidence: options.includeExistingEvidence,
    include_related_objects: options.includeRelatedObjects,
    include_provenance: options.includeProvenance,
    prompt_template_key: options.promptTemplateKey,
    prompt_overrides: Object.keys(options.promptOverrides).length ? options.promptOverrides : undefined,
    temperature: options.temperature,
    max_tokens: options.maxTokens,
  }
}

export type FieldCompletionErrorKind =
  | 'api_not_enabled'
  | 'unsupported_target'
  | 'validation'
  | 'server'
  | 'provider'
  | 'unknown'

export function classifyFieldCompletionError(err: unknown): FieldCompletionErrorKind {
  if (!(err instanceof ApiError)) return 'unknown'
  if (err.status === 404) return 'api_not_enabled'
  if (err.status === 501) return 'unsupported_target'
  if (err.status === 422) return 'validation'
  if (err.status === 503) return 'provider'
  if (err.status >= 500) return 'server'
  const body = err.meta?.responseBody as { detail?: { code?: string } | string } | undefined
  const detail = body?.detail
  if (typeof detail === 'object' && detail?.code === 'TARGET_TYPE_NOT_IMPLEMENTED') {
    return 'unsupported_target'
  }
  if (typeof detail === 'object' && detail?.code === 'PROVIDER_NOT_CONFIGURED') {
    return 'provider'
  }
  return 'unknown'
}

export function formatFieldCompletionErrorMessage(
  err: unknown,
  t: (key: string) => string,
): string {
  const kind = classifyFieldCompletionError(err)
  switch (kind) {
    case 'api_not_enabled':
      return t('dataCenter.apiNotEnabled')
    case 'unsupported_target':
      return t('dataCenter.unsupportedTarget')
    case 'validation':
      return t('dataCenter.fieldCompletionValidationError')
    case 'server':
      return t('dataCenter.fieldCompletionServerError')
    case 'provider':
      return t('dataCenter.fieldCompletionProviderError')
    default:
      if (err instanceof ApiError) {
        const body = err.meta?.responseBody as { detail?: { message?: string } | string } | undefined
        const detail = body?.detail
        if (typeof detail === 'object' && detail?.message) return detail.message
        if (typeof detail === 'string' && detail.length < 300) return detail
      }
      return err instanceof Error ? err.message : String(err)
  }
}

export function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 10)}…` : id
}

export function formatCellValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value.length > 80 ? `${value.slice(0, 77)}…` : value
  try {
    const s = JSON.stringify(value)
    return s.length > 80 ? `${s.slice(0, 77)}…` : s
  } catch {
    return String(value)
  }
}

const APPLIED_OVERLAY_STATUSES = new Set([
  'applied_overlay',
  'applied',
  'applied_direct',
])

export function extractOverlayPatchFromFieldUpdates(
  updates: FieldCompletionUpdateSummary[] | undefined,
): OverlayPatch {
  const patch: OverlayPatch = {}
  for (const u of updates ?? []) {
    if (!APPLIED_OVERLAY_STATUSES.has(u.update_status)) continue
    const value = u.applied_value ?? u.suggested_value
    if (value == null || isFieldValueEmpty(value)) continue
    const tid = String(u.target_id)
    if (!patch[tid]) patch[tid] = {}
    patch[tid][u.field_name] = value
  }
  return patch
}

export function extractOverlayPatchFromItems(
  items: FieldCompletionItem[] | undefined,
): OverlayPatch {
  const patch: OverlayPatch = {}
  for (const item of items ?? []) {
    if (!APPLIED_OVERLAY_STATUSES.has(item.update_status)) continue
    const value = item.applied_value_json ?? item.suggested_value_json
    if (value == null || isFieldValueEmpty(value)) continue
    const tid = String(item.target_id)
    if (!patch[tid]) patch[tid] = {}
    patch[tid][item.field_name] = value
  }
  return patch
}

export function mergeOverlayPatches(...patches: OverlayPatch[]): OverlayPatch {
  const merged: OverlayPatch = {}
  for (const patch of patches) {
    for (const [targetId, fields] of Object.entries(patch)) {
      merged[targetId] = { ...(merged[targetId] ?? {}), ...fields }
    }
  }
  return merged
}

export function mergeOverlayPatchIntoRows<T extends FormalRow>(
  rows: T[],
  patch: OverlayPatch,
): T[] {
  if (Object.keys(patch).length === 0) return rows
  return rows.map(row => {
    const fields = patch[row.id]
    if (!fields || Object.keys(fields).length === 0) return row
    const prev = (row.__fieldCompletionOverlay ?? {}) as Record<string, unknown>
    return {
      ...row,
      __fieldCompletionOverlay: { ...prev, ...fields },
    }
  })
}

export function rowHasPersistedOverlayAttributes(row: FormalRow): boolean {
  const attrs = row.attributes
  if (attrs && typeof attrs === 'object' && !Array.isArray(attrs)) {
    const overlay = (attrs as Record<string, unknown>).formal_field_overlay
      ?? (attrs as Record<string, unknown>).formalFieldOverlay
    if (overlay && typeof overlay === 'object' && Object.keys(overlay as object).length > 0) {
      return true
    }
  }
  const norm = row.normalized_payload_json
  if (norm && typeof norm === 'object' && !Array.isArray(norm)) {
    const overlay = (norm as Record<string, unknown>).formal_field_overlay
    if (overlay && typeof overlay === 'object' && Object.keys(overlay as object).length > 0) {
      return true
    }
  }
  return false
}

export function extractOverlayPatchFromResponses(
  responses: UniversalFieldCompletionResponse[],
): OverlayPatch {
  return mergeOverlayPatches(
    ...responses.map(r => extractOverlayPatchFromFieldUpdates(r.field_updates)),
  )
}
