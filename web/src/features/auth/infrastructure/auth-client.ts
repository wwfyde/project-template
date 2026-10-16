import { requestJson } from '../../../lib/api-client'
import type { AuthSnapshot, AuthUser, SessionResponse } from '../model/auth'
import { normalizeReturnTo } from '../model/return-to'

export class AuthClient {
  private snapshot: AuthSnapshot = { status: 'loading', user: null, providers: [], error: null }
  private csrfToken: string | null = null
  private revision = 0
  private listeners = new Set<() => void>()
  private refreshPromise: Promise<AuthUser | null> | undefined
  private passwordLoginPromise: Promise<void> | undefined
  private passwordSessionPromise: Promise<SessionResponse> | undefined
  private logoutPromise: Promise<void> | undefined

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = () => this.snapshot

  // Revalidate on navigation so an expired or revoked session is not trusted
  // simply because this tab still has an authenticated snapshot in memory.
  ensureSession = () => this.refreshSession()

  refreshSession = () => {
    const mutation = this.logoutPromise ?? this.passwordLoginPromise
    if (mutation) {
      return mutation.then(
        () => this.snapshot.user,
        () => this.snapshot.user,
      )
    }
    this.refreshPromise ??= this.loadSession().finally(() => {
      this.refreshPromise = undefined
    })
    return this.refreshPromise
  }

  startOAuth = (providerId: string, returnTo = '/') => {
    if (this.passwordLoginPromise || this.logoutPromise) {
      throw new Error('An authentication request is already in progress')
    }
    const provider = this.snapshot.providers.find((candidate) => candidate.id === providerId)
    if (!provider?.enabled || !provider.implemented || provider.method !== 'oauth' || !provider.start_path) {
      throw new Error('Authentication provider is unavailable')
    }

    // Only use the local start endpoint returned by the backend registry.
    const expectedPath = `/api/auth/oauth/${encodeURIComponent(provider.id)}/start`
    if (provider.start_path !== expectedPath) {
      throw new Error('Invalid authentication provider start path')
    }
    const query = new URLSearchParams({ return_to: normalizeReturnTo(returnTo) })
    window.location.assign(`${provider.start_path}?${query}`)
  }

  passwordLogin = async (username: string, password: string) => {
    const provider = this.snapshot.providers.find((candidate) => candidate.id === 'password')
    if (!provider?.enabled || !provider.implemented || provider.method !== 'password') {
      throw new Error('Authentication provider is unavailable')
    }
    if (this.passwordLoginPromise || this.logoutPromise) {
      throw new Error('An authentication request is already in progress')
    }

    const revision = ++this.revision
    const request = requestJson<SessionResponse>('/api/auth/password/login', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ username, password }),
    }).then((data) => {
      if (!data.authenticated || !data.user || !data.csrf_token) {
        throw new Error('Unable to verify the authentication session')
      }
      return data
    })
    this.passwordSessionPromise = request
    const completion = request
      .then((data) => {
        if (revision !== this.revision) {
          return
        }
        this.revision += 1
        this.csrfToken = data.csrf_token
        this.publish({ status: 'authenticated', user: data.user, providers: data.providers, error: null })
      })
      .finally(() => {
        this.passwordLoginPromise = undefined
        this.passwordSessionPromise = undefined
      })
    this.passwordLoginPromise = completion
    return completion
  }

  logout = () => {
    if (this.logoutPromise) {
      return this.logoutPromise
    }
    this.revision += 1
    this.logoutPromise = this.endSession(this.passwordSessionPromise).finally(() => {
      this.logoutPromise = undefined
    })
    return this.logoutPromise
  }

  private async endSession(pendingLogin: Promise<SessionResponse> | undefined) {
    // A sign-out initiated during login must also revoke the session being
    // created, without exposing that login as authenticated in the meantime.
    let csrfToken = this.csrfToken
    if (pendingLogin) {
      const data = await pendingLogin.catch(() => null)
      csrfToken = data?.csrf_token ?? csrfToken
    }
    if (!csrfToken) {
      await this.loadSession()
      csrfToken = this.csrfToken
    }
    if (!csrfToken && this.snapshot.status === 'anonymous') {
      return
    }
    if (!csrfToken) {
      throw new Error('Unable to verify the authentication session')
    }

    await requestJson<void>('/api/auth/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
    })
    this.revision += 1
    this.csrfToken = null
    this.publish({ status: 'anonymous', user: null, providers: this.snapshot.providers, error: null })
  }

  private async loadSession(): Promise<AuthUser | null> {
    const revision = this.revision
    try {
      const data = await requestJson<SessionResponse>('/api/auth/session', { cache: 'no-store' })
      if (revision !== this.revision) {
        return this.snapshot.user
      }
      const authenticated = data.authenticated && data.user !== null
      this.csrfToken = authenticated ? data.csrf_token : null
      this.publish({
        status: authenticated ? 'authenticated' : 'anonymous',
        user: authenticated ? data.user : null,
        providers: data.providers,
        error: null,
      })
      return this.snapshot.user
    } catch (error) {
      if (revision !== this.revision) {
        return this.snapshot.user
      }
      this.csrfToken = null
      this.publish({
        status: 'error',
        user: null,
        providers: this.snapshot.providers,
        error: error instanceof Error ? error.message : 'Unable to load authentication session',
      })
      return null
    }
  }

  private publish(next: AuthSnapshot) {
    this.snapshot = next
    this.listeners.forEach((listener) => listener())
  }
}
