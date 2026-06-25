import { ApiError } from '../../../api/client'

const STALE_MAX_LENGTH_50_HINT =
  '后端仍存在 candidate_ids max_length=50 的旧 schema 或服务未重启。请检查 backend/app/schemas/llm_extraction.py 并重启当前后端进程。'

function responseText(error: ApiError): string {
  const body = error.meta?.responseBody
  if (body === undefined || body === null) return error.message
  if (typeof body === 'string') return body
  try {
    return JSON.stringify(body)
  } catch {
    return error.message
  }
}

function isStaleCandidateIdsMaxLength50(text: string): boolean {
  const lower = text.toLowerCase()
  return (
    lower.includes('candidate_ids')
    && (lower.includes('max_length') || lower.includes('most 50 items') || lower.includes('at most 50'))
    && lower.includes('50')
  )
}

function isDuplicateCommitProgressError(text: string): boolean {
  const lower = text.toLowerCase()
  return lower.includes('commit_progress') && lower.includes('multiple values for keyword argument')
}

/** User-friendly API error text; avoids dumping long candidate_ids JSON. */
export function formatExtractionApiError(error: unknown, maxLen = 500): string {
  if (error instanceof ApiError) {
    const raw = responseText(error)
    if (isStaleCandidateIdsMaxLength50(raw)) {
      return STALE_MAX_LENGTH_50_HINT
    }
    if (isDuplicateCommitProgressError(raw)) {
      return '后端工作流状态更新失败：重复传入 commit_progress 参数。请更新后端后重试。'
    }
    const msg = error.message
    if (isDuplicateCommitProgressError(msg)) {
      return '后端工作流状态更新失败：重复传入 commit_progress 参数。请更新后端后重试。'
    }
    return msg.length > maxLen ? `${msg.slice(0, maxLen)}…` : msg
  }
  const msg = error instanceof Error ? error.message : String(error)
  if (isStaleCandidateIdsMaxLength50(msg)) {
    return STALE_MAX_LENGTH_50_HINT
  }
  if (isDuplicateCommitProgressError(msg)) {
    return '后端工作流状态更新失败：重复传入 commit_progress 参数。请更新后端后重试。'
  }
  return msg.length > maxLen ? `${msg.slice(0, maxLen)}…` : msg
}
