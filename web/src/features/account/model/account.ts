import type { AuthProviderSummary, AuthUser } from '../../auth'

export type AccountIdentity = {
  id: string
  provider: string
  username: string | null
  enabled: boolean
  current: boolean
  can_unlink: boolean
}

export type AccountSummary = {
  id: string
  name: string | null
  structure: 'personal' | 'workspace'
}

export type AccountRead = {
  account: AccountSummary
  user: AuthUser
  identities: AccountIdentity[]
  providers: AuthProviderSummary[]
  reauthentication: { required: boolean; expires_in: number }
}

export type ProfileUpdate = { display_name: string; avatar_url: string | null }
export type PasswordUpdate = { username?: string; password: string; current_password?: string }

export const accountErrorCodes = [
  'identity_conflict',
  'provider_already_linked',
  'reauthentication_required',
  'oauth_failed',
  'oauth_denied',
  'session_changed',
  'identity_mismatch',
  'account_changed',
  'account_unavailable',
  'identity_not_linked',
  'last_login_method',
  'username_required',
  'username_immutable',
  'invalid_username',
  'invalid_password',
  'current_password_required',
  'invalid_current_password',
  'reauthentication_failed',
  'provider_unavailable',
  'password_mismatch',
  'username_conflict',
  'invalid_profile',
  'request_failed',
] as const

export type AccountErrorCode = (typeof accountErrorCodes)[number]
export type AccountSearch = {
  account_action?: 'linked' | 'reauthenticated'
  account_error?: AccountErrorCode
}

export function accountErrorCode(code: unknown): AccountErrorCode {
  return accountErrorCodes.includes(code as AccountErrorCode) ? (code as AccountErrorCode) : 'request_failed'
}

export function parseAccountSearch(search: Record<string, unknown>): AccountSearch {
  return {
    account_action:
      search.account_action === 'linked' || search.account_action === 'reauthenticated'
        ? search.account_action
        : undefined,
    account_error: typeof search.account_error === 'string' ? accountErrorCode(search.account_error) : undefined,
  }
}
