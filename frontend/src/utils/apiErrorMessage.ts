import { ApiError } from '../api/client'

interface BoundFileDetail {
  original_filename?: string
  reason?: string
}

interface StructuredDetail {
  message?: string
  code?: string
  file_id?: string
  file_status?: string
  suggestion?: string
  bound_files?: BoundFileDetail[]
}

export function formatApiErrorDetail(detail: unknown): string | null {
  if (!detail || typeof detail !== 'object') return null
  const d = detail as StructuredDetail
  const parts: string[] = []
  if (d.message) parts.push(d.message)
  if (Array.isArray(d.bound_files)) {
    for (const bf of d.bound_files) {
      const line = [bf.original_filename, bf.reason].filter(Boolean).join(': ')
      if (line) parts.push(line)
    }
  }
  if (d.file_id) parts.push(`file_id=${d.file_id}`)
  if (d.file_status) parts.push(`status=${d.file_status}`)
  if (d.suggestion) parts.push(d.suggestion)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function formatApiErrorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) return String(e)
  const body = e.meta?.responseBody as { detail?: unknown } | undefined
  const formatted = formatApiErrorDetail(body?.detail)
  if (formatted) return formatted
  return e.message
}
