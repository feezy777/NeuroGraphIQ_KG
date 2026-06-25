/** Normalize optional UUID fields before API requests. Empty strings become undefined. */
export function normalizeOptionalUuid(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed === '') return undefined
    return trimmed
  }
  return String(value)
}

/** Normalize optional string fields. Empty/whitespace-only strings become undefined. */
export function normalizeOptionalString(value: unknown): string | undefined {
  return normalizeOptionalUuid(value)
}

/** Remove keys whose values are undefined (keeps null). */
export function omitUndefined<T extends Record<string, unknown>>(obj: T): Partial<T> {
  const out: Partial<T> = {}
  for (const [key, val] of Object.entries(obj)) {
    if (val !== undefined) {
      out[key as keyof T] = val as T[keyof T]
    }
  }
  return out
}

/** Filter empty strings from UUID id lists. */
export function filterNonEmptyIds(ids: unknown): string[] {
  if (!Array.isArray(ids)) return []
  return ids
    .filter((id): id is string => typeof id === 'string' && id.trim() !== '')
    .map(id => id.trim())
}
