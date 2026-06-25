import { ApiError } from '../api/client'

export interface DuplicateExistingFile {
  id: string
  resource_id?: string
  original_filename?: string
  file_type?: string
  file_role?: string
  status?: string
  file_size_bytes?: number
  sha256?: string
  created_at?: string
  updated_at?: string
  intermediate_status?: string | null
  latest_intermediate_artifact_id?: string | null
  latest_intermediate_kind?: string | null
  latest_intermediate_row_count?: number | null
}

export interface DuplicateFileDetail {
  code?: string
  message?: string
  resource_id?: string
  sha256?: string
  existing_file?: DuplicateExistingFile
  suggestion?: string
}

function asDetail(raw: unknown): DuplicateFileDetail | null {
  if (!raw || typeof raw !== 'object') return null
  return raw as DuplicateFileDetail
}

export function isDuplicateInactiveCode(code?: string): boolean {
  return (
    code === 'DUPLICATE_RESOURCE_FILE_INACTIVE'
    || code === 'DUPLICATE_RESOURCE_FILE_ARCHIVED'
  )
}

export function isInactiveExistingFile(existing?: DuplicateExistingFile): boolean {
  return existing?.status !== undefined && existing.status !== 'active'
}

export function parseDuplicateFileDetail(error: unknown): DuplicateFileDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.meta?.responseBody as { detail?: unknown } | undefined
  const detail = asDetail(body?.detail)
  if (!detail) return null

  const code = detail.code ?? ''
  const message = detail.message ?? ''
  if (
    code === 'DUPLICATE_RESOURCE_FILE'
    || isDuplicateInactiveCode(code)
    || message.includes('duplicate file for this resource')
    || message.includes('already exists for this resource')
    || message.includes('same sha256')
    || message.includes('not active')
  ) {
    return detail
  }
  return null
}

export function isMacro96DuplicateFile(
  existing: DuplicateExistingFile | { file_role?: string | null; latest_intermediate_kind?: string | null; original_filename?: string | null } | undefined,
): boolean {
  if (!existing) return false
  if (existing.file_role === 'macro_region_pool_source') return true
  if (existing.latest_intermediate_kind === 'macro_region_table') return true
  const name = (existing.original_filename ?? '').toLowerCase()
  return name.includes('brain volume')
}

export function duplicateDetailIsInactive(detail: DuplicateFileDetail): boolean {
  if (isDuplicateInactiveCode(detail.code)) return true
  return isInactiveExistingFile(detail.existing_file)
}
