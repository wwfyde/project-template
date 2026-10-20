import type { Auth } from '../../auth'
import type { SessionResponse } from '../../auth/model/auth'
import type { AccountRead, PasswordUpdate, ProfileUpdate } from '../model/account'

type AccountAuth = Pick<Auth, 'authenticatedRequest'>
type AuthorizationResponse = { authorization_url: string }

const authorizationEndpoints: Record<string, string> = {
  google: 'https://accounts.google.com/o/oauth2/v2/auth',
  dingtalk: 'https://login.dingtalk.com/oauth2/auth',
}

export function validateAuthorizationUrl(provider: string, value: string): string {
  const endpoint = authorizationEndpoints[provider]
  const url = new URL(value)
  if (!endpoint || `${url.origin}${url.pathname}` !== endpoint || url.username || url.password || url.hash) {
    throw new Error('Invalid account authorization URL')
  }
  return url.href
}

export function createAccountClient(auth: AccountAuth) {
  const request = auth.authenticatedRequest
  return {
    read: () => request<AccountRead>('/api/account'),
    updateProfile: (profile: ProfileUpdate) =>
      request<AccountRead>('/api/account/profile', {
        method: 'PATCH',
        body: JSON.stringify(profile),
      }),
    unlink: (identityId: string) =>
      request<{ requires_login: boolean }>(`/api/account/identities/${encodeURIComponent(identityId)}`, {
        method: 'DELETE',
      }),
    setPassword: (password: PasswordUpdate) =>
      request<{ requires_login: false }>('/api/account/password', {
        method: 'PUT',
        body: JSON.stringify(password),
      }),
    reauthenticatePassword: (password: string) =>
      request<SessionResponse>('/api/account/reauth/password', {
        method: 'POST',
        body: JSON.stringify({ password }),
      }),
    startOAuth: async (provider: string, reauthenticate = false) => {
      if (!authorizationEndpoints[provider]) {
        throw new Error('Authentication provider is unavailable')
      }
      const path = reauthenticate
        ? `/api/account/reauth/oauth/${provider}/start`
        : `/api/account/identities/${provider}/start`
      const data = await request<AuthorizationResponse>(path, { method: 'POST' })
      window.location.assign(validateAuthorizationUrl(provider, data.authorization_url))
    },
  }
}
