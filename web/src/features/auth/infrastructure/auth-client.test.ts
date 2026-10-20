import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SessionResponse } from '../model/auth'
import { AuthClient } from './auth-client'

const session: SessionResponse = {
  authenticated: true,
  user: {
    id: 'user-1',
    provider: 'google',
    display_name: 'Example User',
    avatar_url: null,
    email: 'user@example.test',
    phone: null,
    account_id: 'account-1',
    tenant_id: 'account-1',
  },
  providers: [
    { id: 'google', method: 'oauth', implemented: true, enabled: true, start_path: '/api/auth/oauth/google/start' },
    { id: 'phone', method: 'otp', implemented: false, enabled: true, start_path: null },
    { id: 'password', method: 'password', implemented: true, enabled: true, start_path: null },
  ],
  csrf_token: 'csrf-session-token',
}

const fetchMock = vi.fn<typeof fetch>()
const assignMock = vi.fn()
const anonymousSession: SessionResponse = { ...session, authenticated: false, user: null, csrf_token: null }
const passwordSession: SessionResponse = { ...session, user: { ...session.user!, provider: 'password' } }

function pendingResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((onResolve) => {
    resolve = onResolve
  })
  return { promise, resolve }
}

beforeEach(() => {
  fetchMock.mockReset()
  assignMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('window', { location: { origin: 'https://app.example.test', assign: assignMock } })
})

afterEach(() => vi.unstubAllGlobals())

describe('AuthClient', () => {
  it('protects account mutations with CSRF and refreshes the rotated session before the next mutation', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    const rotated = { ...session, csrf_token: 'rotated-account-csrf' }
    fetchMock.mockResolvedValueOnce(Response.json({ requires_login: false }))
    fetchMock.mockResolvedValueOnce(Response.json(rotated))
    await client.authenticatedRequest('/api/account/password', {
      method: 'PUT',
      headers: { 'X-CSRF-Token': 'do-not-trust-caller' },
      body: JSON.stringify({ password: 'private-password' }),
    })
    const first = fetchMock.mock.calls[1][1]
    expect(first?.credentials).toBe('include')
    expect(new Headers(first?.headers).get('X-CSRF-Token')).toBe(session.csrf_token)
    expect(new Headers(first?.headers).get('Request-ID')).toMatch(/^[\da-f-]{36}$/)
    expect(fetchMock.mock.calls[2][0]).toBe('/api/auth/session')
    expect(JSON.stringify(client.getSnapshot())).not.toContain('private-password')

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await client.logout()
    expect(new Headers(fetchMock.mock.calls[3][1]?.headers).get('X-CSRF-Token')).toBe(rotated.csrf_token)
  })

  it('does not replay account mutations when recent authentication is required', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: 'reauthentication_required', message: 'Verify first' } }, { status: 403 }),
    )
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await expect(
      client.authenticatedRequest('/api/account/identities/google/start', { method: 'POST' }),
    ).rejects.toMatchObject({ code: 'reauthentication_required', status: 403 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(client.getSnapshot().status).toBe('authenticated')
  })

  it('refreshes after a failed credential change and discards a revoked session without replaying it', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    fetchMock.mockResolvedValueOnce(Response.json({ detail: 'Session rotation unavailable' }, { status: 503 }))
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await expect(client.authenticatedRequest('/api/account/password', { method: 'PUT' })).rejects.toMatchObject({
      status: 503,
    })
    expect(client.getSnapshot()).toMatchObject({ status: 'anonymous', user: null })
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/api/auth/session',
      '/api/account/password',
      '/api/auth/session',
    ])
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await expect(client.authenticatedRequest('/api/account/password', { method: 'PUT' })).rejects.toThrow(
      'Unable to verify',
    )
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/account/password')).toHaveLength(1)
  })

  it('revalidates the user session after an unauthorized account read', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    fetchMock.mockResolvedValueOnce(Response.json({ detail: 'Not authenticated' }, { status: 401 }))
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await expect(client.authenticatedRequest('/api/account')).rejects.toMatchObject({ status: 401 })
    expect(client.getSnapshot().status).toBe('anonymous')
  })

  it('invalidates stale reads, serializes account changes, and waits for their session refresh', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    const oldRefresh = pendingResponse()
    fetchMock.mockReturnValueOnce(oldRefresh.promise)
    const oldRead = client.refreshSession()
    const mutation = pendingResponse()
    fetchMock.mockReturnValueOnce(mutation.promise)
    const pendingMutation = client.authenticatedRequest('/api/account/reauth/password', { method: 'POST' })
    const pendingRefresh = client.refreshSession()
    await expect(client.authenticatedRequest('/api/account/password', { method: 'PUT' })).rejects.toThrow(
      'already in progress',
    )
    const rotated = {
      ...session,
      csrf_token: 'reauthenticated-csrf',
      user: { ...session.user!, display_name: 'Updated name' },
    }
    fetchMock.mockResolvedValueOnce(Response.json(rotated))
    mutation.resolve(Response.json(rotated))
    await pendingMutation
    expect(await pendingRefresh).toEqual(rotated.user)
    oldRefresh.resolve(Response.json(session))
    await oldRead
    expect(client.getSnapshot().user?.display_name).toBe('Updated name')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await client.logout()
    expect(new Headers(fetchMock.mock.calls[4][1]?.headers).get('X-CSRF-Token')).toBe('reauthenticated-csrf')
  })

  it('waits for an account mutation before logging out with the rotated token', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(session))
    await client.refreshSession()
    const mutation = pendingResponse()
    fetchMock.mockReturnValueOnce(mutation.promise)
    const pendingMutation = client.authenticatedRequest('/api/account/password', { method: 'PUT' })
    const pendingLogout = client.logout()
    fetchMock.mockResolvedValueOnce(Response.json({ ...session, csrf_token: 'post-mutation-csrf' }))
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    mutation.resolve(Response.json({ requires_login: false }))
    await Promise.all([pendingMutation, pendingLogout])
    expect(fetchMock.mock.calls[3][0]).toBe('/api/auth/logout')
    expect(new Headers(fetchMock.mock.calls[3][1]?.headers).get('X-CSRF-Token')).toBe('post-mutation-csrf')
    expect(client.getSnapshot().status).toBe('anonymous')
  })

  it('deduplicates concurrent session checks and revalidates on the next navigation', async () => {
    fetchMock.mockImplementation(async () => Response.json(session))
    const client = new AuthClient()
    const results = await Promise.all([client.ensureSession(), client.ensureSession()])
    expect(results).toEqual([session.user, session.user])
    expect(fetchMock).toHaveBeenCalledTimes(1)

    fetchMock.mockResolvedValueOnce(Response.json({ ...session, authenticated: false, user: null, csrf_token: null }))
    expect(await client.ensureSession()).toBeNull()
    expect(client.getSnapshot().status).toBe('anonymous')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('uses the enabled OAuth registry and a safe return location', async () => {
    fetchMock.mockResolvedValue(Response.json(session))
    const client = new AuthClient()
    await client.refreshSession()
    client.startOAuth('google', '/admin?tab=users')
    expect(assignMock).toHaveBeenLastCalledWith('/api/auth/oauth/google/start?return_to=%2Fadmin%3Ftab%3Dusers')
    client.startOAuth('google', 'https://attacker.example')
    expect(assignMock).toHaveBeenLastCalledWith('/api/auth/oauth/google/start?return_to=%2F')
    expect(() => client.startOAuth('phone')).toThrow('unavailable')
    expect(() => client.startOAuth('unknown')).toThrow('unavailable')
  })

  it('rejects disabled providers and external OAuth start endpoints', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...session, providers: [{ ...session.providers[0], enabled: false }] }),
    )
    await client.refreshSession()
    expect(() => client.startOAuth('google')).toThrow('unavailable')
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...session, providers: [{ ...session.providers[0], start_path: 'https://attacker.example' }] }),
    )
    await client.refreshSession()
    expect(() => client.startOAuth('google')).toThrow('Invalid')
    expect(assignMock).not.toHaveBeenCalled()
  })

  it('sends the server CSRF token and clears user state only after successful logout', async () => {
    fetchMock.mockResolvedValueOnce(Response.json(session))
    const client = new AuthClient()
    await client.refreshSession()
    fetchMock.mockResolvedValueOnce(Response.json({ detail: 'Forbidden' }, { status: 403 }))
    await expect(client.logout()).rejects.toThrow('Forbidden')
    expect(client.getSnapshot().user).toEqual(session.user)

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await client.logout()
    expect(client.getSnapshot().status).toBe('anonymous')
    expect(client.getSnapshot().user).toBeNull()
    const request = fetchMock.mock.calls[2][1]
    expect(request?.method).toBe('POST')
    expect(new Headers(request?.headers).get('X-CSRF-Token')).toBe(session.csrf_token)
  })

  it('does not restore an authenticated snapshot from a session request that predates logout', async () => {
    fetchMock.mockResolvedValueOnce(Response.json(session))
    const client = new AuthClient()
    await client.refreshSession()
    let resolveRefresh!: (response: Response) => void
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveRefresh = resolve
      }),
    )
    const pendingRefresh = client.refreshSession()
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await client.logout()
    resolveRefresh(Response.json(session))
    expect(await pendingRefresh).toBeNull()
    expect(client.getSnapshot().status).toBe('anonymous')
  })

  it('fails closed when the session service is unavailable and supports retry', async () => {
    const client = new AuthClient()
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    expect(await client.ensureSession()).toBeNull()
    expect(client.getSnapshot()).toMatchObject({ status: 'error', user: null })
    fetchMock.mockResolvedValueOnce(Response.json(session))
    expect(await client.refreshSession()).toEqual(session.user)
    expect(client.getSnapshot().status).toBe('authenticated')
  })

  it('logs in with credentials and uses the returned session CSRF token to log out', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await client.refreshSession()
    fetchMock.mockResolvedValueOnce(Response.json(passwordSession))
    await client.passwordLogin('example-user', 'private-password')

    expect(client.getSnapshot()).toMatchObject({ status: 'authenticated', user: passwordSession.user })
    const [path, request] = fetchMock.mock.calls[1]
    expect(path).toBe('/api/auth/password/login')
    expect(request?.method).toBe('POST')
    expect(request?.credentials).toBe('include')
    expect(new Headers(request?.headers).get('X-Requested-With')).toBe('XMLHttpRequest')
    expect(JSON.parse(request?.body as string)).toEqual({ username: 'example-user', password: 'private-password' })
    expect(JSON.stringify(client.getSnapshot())).not.toContain('private-password')

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await client.logout()
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('X-CSRF-Token')).toBe(passwordSession.csrf_token)
    expect(client.getSnapshot().status).toBe('anonymous')
  })

  it.each([
    { id: 'password', method: 'password', implemented: true, enabled: false },
    { id: 'password', method: 'password', implemented: false, enabled: true },
    { id: 'password', method: 'oauth', implemented: true, enabled: true },
    { id: 'other-password', method: 'password', implemented: true, enabled: true },
  ])('rejects password login unless the configured provider is available: %j', async (provider) => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json({ ...anonymousSession, providers: [provider] }))
    await client.refreshSession()
    await expect(client.passwordLogin('example-user', 'private-password')).rejects.toThrow('unavailable')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('preserves session state after invalid credentials and permits retry', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await client.refreshSession()
    const originalSnapshot = client.getSnapshot()
    fetchMock.mockResolvedValueOnce(Response.json({ detail: 'Invalid username or password' }, { status: 401 }))
    await expect(client.passwordLogin('example-user', 'wrong-password')).rejects.toThrow('Invalid username or password')
    expect(client.getSnapshot()).toBe(originalSnapshot)
    expect(JSON.stringify(client.getSnapshot())).not.toContain('wrong-password')

    fetchMock.mockResolvedValueOnce(Response.json(passwordSession))
    await client.passwordLogin('example-user', 'private-password')
    expect(client.getSnapshot().status).toBe('authenticated')
  })

  it('does not overwrite a password login with an older anonymous session response', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await client.refreshSession()
    const refresh = pendingResponse()
    fetchMock.mockReturnValueOnce(refresh.promise)
    const pendingRefresh = client.refreshSession()
    fetchMock.mockResolvedValueOnce(Response.json(passwordSession))
    await client.passwordLogin('example-user', 'private-password')
    refresh.resolve(Response.json(anonymousSession))

    expect(await pendingRefresh).toEqual(passwordSession.user)
    expect(client.getSnapshot().status).toBe('authenticated')
  })

  it('waits for an active password login during refresh and rejects duplicate sign-in attempts', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await client.refreshSession()
    const login = pendingResponse()
    fetchMock.mockReturnValueOnce(login.promise)
    const pendingLogin = client.passwordLogin('example-user', 'private-password')
    const pendingRefresh = client.refreshSession()
    await expect(client.passwordLogin('another-user', 'another-password')).rejects.toThrow('already in progress')
    expect(() => client.startOAuth('google')).toThrow('already in progress')
    expect(fetchMock).toHaveBeenCalledTimes(2)

    login.resolve(Response.json(passwordSession))
    await pendingLogin
    expect(await pendingRefresh).toEqual(passwordSession.user)
  })

  it('gives logout priority over a pending password login and revokes its newly created session', async () => {
    const client = new AuthClient()
    fetchMock.mockResolvedValueOnce(Response.json(anonymousSession))
    await client.refreshSession()
    const snapshots: string[] = []
    client.subscribe(() => snapshots.push(client.getSnapshot().status))
    const login = pendingResponse()
    fetchMock.mockReturnValueOnce(login.promise)
    const pendingLogin = client.passwordLogin('example-user', 'private-password')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    const pendingLogout = client.logout()
    expect(client.logout()).toBe(pendingLogout)
    await expect(client.passwordLogin('example-user', 'private-password')).rejects.toThrow('already in progress')

    login.resolve(Response.json(passwordSession))
    await Promise.all([pendingLogin, pendingLogout])
    expect(fetchMock.mock.calls[2][0]).toBe('/api/auth/logout')
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('X-CSRF-Token')).toBe(passwordSession.csrf_token)
    expect(snapshots).not.toContain('authenticated')
    expect(client.getSnapshot()).toMatchObject({ status: 'anonymous', user: null })
  })
})
