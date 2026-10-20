export type AuthProviderMethod = 'oauth' | 'otp' | 'password'
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'error'

export type AuthUser = {
  id: string
  provider: string
  display_name: string
  avatar_url: string | null
  email: string | null
  phone: string | null
  account_id: string
  /** @deprecated Use account_id; retained for compatibility with older API clients. */
  tenant_id: string | null
}

export type AuthProviderSummary = {
  id: string
  method: AuthProviderMethod
  enabled: boolean
  implemented: boolean
  start_path?: string | null
}

export type SessionResponse = {
  authenticated: boolean
  user: AuthUser | null
  providers: AuthProviderSummary[]
  csrf_token: string | null
}

export type AuthSnapshot = {
  status: AuthStatus
  user: AuthUser | null
  providers: AuthProviderSummary[]
  error: string | null
}

export type Auth = AuthSnapshot & {
  ensureSession: () => Promise<AuthUser | null>
  refreshSession: () => Promise<AuthUser | null>
  startOAuth: (providerId: string, returnTo?: string) => void
  passwordLogin: (username: string, password: string) => Promise<void>
  authenticatedRequest: <T>(path: string, init?: RequestInit) => Promise<T>
  logout: () => Promise<void>
}

export type RouterAuth = Pick<Auth, 'ensureSession'>
