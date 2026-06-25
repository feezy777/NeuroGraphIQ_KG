/** Backend FastAPI/Pydantic enforces query limit <= 200 for list APIs. */
export const API_MAX_LIMIT = 200

export const LLM_TABLE_DEFAULT_PAGE_SIZE = 100

export const LLM_TABLE_PAGE_SIZE_OPTIONS = [50, 100, 200] as const

export function clampApiLimit(value: number | undefined | null): number {
  if (!Number.isFinite(value as number)) return API_MAX_LIMIT
  return Math.max(1, Math.min(API_MAX_LIMIT, Number(value)))
}

export function isLimitExceededError(error: string | null | undefined): boolean {
  if (!error) return false
  return (
    error.includes('422') &&
    (error.includes('limit') || error.includes('less_than_equal'))
  )
}
