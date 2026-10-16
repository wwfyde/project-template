import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, requestJson } from './api-client'

afterEach(() => vi.unstubAllGlobals())

describe('requestJson', () => {
  it('sends cookies and a distinct request ID without claiming an identity or inventing a trace', async () => {
    const fetch = vi.fn().mockImplementation(async () => Response.json({ ok: true }))
    vi.stubGlobal('fetch', fetch)

    await requestJson('/api/auth/session')
    await requestJson('/api/auth/session')

    const first = fetch.mock.calls[0][1] as RequestInit
    const second = fetch.mock.calls[1][1] as RequestInit
    const firstHeaders = new Headers(first.headers)
    const secondHeaders = new Headers(second.headers)
    expect(first.credentials).toBe('include')
    expect(firstHeaders.get('Request-ID')).toMatch(/^[\da-f-]{36}$/)
    expect(firstHeaders.get('Request-ID')).not.toBe(secondHeaders.get('Request-ID'))
    expect(firstHeaders.has('User-ID')).toBe(false)
    expect(firstHeaders.has('Tenant-ID')).toBe(false)
    expect(firstHeaders.has('traceparent')).toBe(false)
  })

  it('preserves caller-supplied CSRF and tracing headers and accepts an empty logout response', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetch)
    const traceparent = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01'

    await expect(
      requestJson('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': 'token', traceparent } }),
    ).resolves.toBeUndefined()
    const headers = new Headers(fetch.mock.calls[0][1].headers)
    expect(headers.get('X-CSRF-Token')).toBe('token')
    expect(headers.get('traceparent')).toBe(traceparent)
  })

  it('retains server request IDs in structured API errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ detail: 'Forbidden' }, { status: 403, headers: { 'Request-ID': 'server-id' } }),
        ),
    )
    const error = await requestJson('/api/auth/logout').catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(ApiRequestError)
    expect(error).toMatchObject({ status: 403, requestId: 'server-id', message: 'Forbidden' })
  })

  it.each(['https://attacker.example/api/session', '//attacker.example/api/session', '/api\\attacker', '/other'])(
    'rejects destinations outside the local API: %s',
    async (path) => {
      const fetch = vi.fn()
      vi.stubGlobal('fetch', fetch)
      await expect(requestJson(path)).rejects.toThrow('local /api path')
      expect(fetch).not.toHaveBeenCalled()
    },
  )
})
