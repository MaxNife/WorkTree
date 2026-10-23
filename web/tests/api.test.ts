import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiGet, apiSend, buildUrl } from '@/api/client'

function respond(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('buildUrl', () => {
  it('substitutes and encodes path parameters', () => {
    expect(buildUrl('/api/activities/{name}/test', { path: { name: 'a b/c' } })).toBe('/api/activities/a%20b%2Fc/test')
  })

  it('adds only defined query values', () => {
    expect(buildUrl('/api/x', { query: { a: 1, b: undefined, c: false } })).toBe('/api/x?a=1&c=false')
  })

  it('rejects a missing path parameter', () => {
    expect(() => buildUrl('/api/activities/{name}/test')).toThrow('missing path parameter: name')
  })
})

describe('fetch helpers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns parsed JSON and sends same-origin credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(apiGet('/health')).resolves.toEqual({ status: 'ok' })
    expect(fetchMock).toHaveBeenCalledWith('/health', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('raises ApiError with the backend error code and message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(403, { error: { code: 'forbidden', message: 'No access' } })))
    const error = await apiGet('/health').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'forbidden', message: 'No access' })
  })

  it('falls back to the status text for a non-JSON error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('boom', { status: 502, statusText: 'Bad Gateway' })))
    await expect(apiGet('/health')).rejects.toMatchObject({ status: 502, message: 'Bad Gateway' })
  })

  it('sends JSON bodies and handles 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(apiSend('POST', '/api/auth/logout', { a: 1 })).resolves.toBeUndefined()
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"a":1}')
  })
})
