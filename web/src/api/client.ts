// A small typed fetch client over the generated OpenAPI types (schema.d.ts).
import type { paths } from './schema'

type Json<Op> = Op extends { responses: { 200: { content: { 'application/json': infer R } } } } ? R : unknown

/** Paths that have a GET operation. */
export type GetPath = {
  [P in keyof paths]: NonNullable<paths[P]['get']> extends never ? never : P
}[keyof paths]

export type GetResponse<P extends GetPath> = Json<NonNullable<paths[P]['get']>>

export interface RequestOptions {
  path?: Record<string, string>
  query?: Record<string, string | number | boolean | string[] | undefined>
  signal?: AbortSignal
}

/** An error response from the API (the backend wraps errors as `{error: {code, message}}`). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Substitute `{name}` placeholders and append the query string. */
export function buildUrl(template: string, options: RequestOptions = {}): string {
  let url = template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = options.path?.[key]
    if (value === undefined) throw new Error(`missing path parameter: ${key}`)
    return encodeURIComponent(value)
  })
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item))
    else if (value !== undefined) query.set(key, String(value))
  }
  const text = query.toString()
  if (text) url += (url.includes('?') ? '&' : '?') + text
  return url
}

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return (response.status === 204 ? undefined : await response.json()) as T
  let code = 'http_error'
  let message = response.statusText || `HTTP ${response.status}`
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    // not JSON; keep the status text
  }
  throw new ApiError(response.status, code, message)
}

export async function apiGet<P extends GetPath>(path: P, options: RequestOptions = {}): Promise<GetResponse<P>> {
  const response = await fetch(buildUrl(path, options), {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  })
  return parse<GetResponse<P>>(response)
}

// Mutating routes require the session's CSRF token in `X-CSRF-Token`. The session store sets it from
// the login and /api/auth/me responses; the readable `uaf_csrf` cookie is the fallback.
const CSRF_COOKIE = 'uaf_csrf'
let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

function currentCsrfToken(): string | null {
  if (csrfToken) return csrfToken
  if (typeof document === 'undefined') return null
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${CSRF_COOKIE}=`))
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null
}

export async function apiSend<T>(method: 'POST' | 'PUT' | 'PATCH' | 'DELETE', url: string, body?: unknown): Promise<T> {
  const token = currentCsrfToken()
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return parse<T>(response)
}
