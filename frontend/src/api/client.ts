import { emitWorkbenchLog } from '../logging/logBridge'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly meta?: {
      url?: string
      method?: string
      responseBody?: unknown
      requestBodyPreview?: unknown
      statusText?: string
    },
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type QueryParams = Record<string, string | number | boolean | null | undefined>

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '') as string

function buildUrl(path: string, params?: QueryParams): string {
  const sp = new URLSearchParams()
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') {
        sp.set(k, String(v))
      }
    }
  }
  const qs = sp.toString()
  return `${BASE}${path}${qs ? `?${qs}` : ''}`
}

export function buildApiUrl(path: string, params?: QueryParams): string {
  return buildUrl(path, params)
}

function previewBody(body: unknown): unknown {
  if (body === undefined) return undefined
  if (body instanceof FormData) return '[FormData]'
  try {
    const s = JSON.stringify(body)
    if (s.length > 4000) return { _truncated: true, preview: s.slice(0, 4000) }
    return body
  } catch {
    return String(body)
  }
}

async function handleError(
  res: Response,
  ctx: { url: string; method: string; requestBodyPreview?: unknown },
): Promise<never> {
  let responseBody: unknown = null
  let detailStr = res.statusText
  try {
    const text = await res.text()
    if (text) {
      try {
        responseBody = JSON.parse(text) as unknown
        const body = responseBody as { detail?: unknown }
        if (typeof body.detail === 'string') detailStr = body.detail
        else if (body.detail !== undefined) detailStr = JSON.stringify(body.detail)
      } catch {
        responseBody = text
        detailStr = text.length > 2000 ? `${text.slice(0, 2000)}…` : text
      }
    }
  } catch {
    // ignore read errors
  }

  emitWorkbenchLog({
    level: res.status >= 500 ? 'error' : 'warning',
    source: 'api',
    title: `${ctx.method} ${res.status} ${ctx.url}`,
    message: detailStr,
    method: ctx.method,
    url: ctx.url,
    status: res.status,
    statusText: res.statusText,
    requestBodyPreview: ctx.requestBodyPreview,
    responseBody,
    detail: responseBody,
    tags: ['api', `http-${res.status}`],
  })

  throw new ApiError(res.status, `HTTP ${res.status}: ${detailStr}`, {
    url: ctx.url,
    method: ctx.method,
    responseBody,
    requestBodyPreview: ctx.requestBodyPreview,
    statusText: res.statusText,
  })
}

export async function getJson<T>(path: string, params?: QueryParams): Promise<T> {
  const url = buildUrl(path, params)
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) return handleError(res, { url, method: 'GET' })
  return res.json() as Promise<T>
}

export async function postJson<T>(path: string, body?: unknown, params?: QueryParams): Promise<T> {
  const url = buildUrl(path, params)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) return handleError(res, { url, method: 'POST', requestBodyPreview: previewBody(body) })
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export async function patchJson<T>(path: string, body?: unknown, params?: QueryParams): Promise<T> {
  const url = buildUrl(path, params)
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) return handleError(res, { url, method: 'PATCH', requestBodyPreview: previewBody(body) })
  return res.json() as Promise<T>
}

export async function deleteJson<T>(path: string, params?: QueryParams): Promise<T> {
  const url = buildUrl(path, params)
  const res = await fetch(url, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) return handleError(res, { url, method: 'DELETE' })
  return res.json() as Promise<T>
}

export async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  const url = buildUrl(path)
  const res = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: formData,
  })
  if (!res.ok) return handleError(res, { url, method: 'POST', requestBodyPreview: '[FormData]' })
  return res.json() as Promise<T>
}
