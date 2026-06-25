import { ApiError } from '../api/client'
import type { AtlasResource } from '../api/endpoints'

export interface ResourceDependencyCounts {
  files?: number
  batches?: number
  raw_rows?: number
  candidates?: number
  final_regions?: number
}

export interface DuplicateResourceDetail {
  code?: string
  message?: string
  resource_code?: string
  existing_resource?: Partial<AtlasResource> & { id: string }
  can_restore?: boolean
  can_purge?: boolean
  can_destructive_delete?: boolean
  delete_preview_url?: string
  dependency_counts?: ResourceDependencyCounts
  suggestion?: string
}

function asDetail(raw: unknown): DuplicateResourceDetail | null {
  if (!raw || typeof raw !== 'object') return null
  return raw as DuplicateResourceDetail
}

export function parseDuplicateResourceDetail(error: unknown): DuplicateResourceDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.meta?.responseBody as { detail?: unknown } | undefined
  const detail = asDetail(body?.detail)
  if (!detail) return null
  if (detail.code === 'DUPLICATE_RESOURCE_CODE') return detail
  if (detail.message?.toLowerCase().includes('resource code already exists')) return detail
  if (detail.message?.toLowerCase().includes('resource_code already exists')) return detail
  if (detail.resource_code) return { ...detail, code: 'DUPLICATE_RESOURCE_CODE' }
  return null
}

export function parseResourceHasDependencies(error: unknown): DuplicateResourceDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.meta?.responseBody as { detail?: unknown } | undefined
  const detail = asDetail(body?.detail)
  if (detail?.code === 'RESOURCE_HAS_DEPENDENCIES') return detail
  return null
}

export function formatDependencyCounts(counts?: ResourceDependencyCounts): string {
  if (!counts) return ''
  return Object.entries(counts)
    .filter(([, v]) => (v ?? 0) > 0)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ')
}
