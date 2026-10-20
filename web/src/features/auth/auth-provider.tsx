import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react'

import { AuthContext } from './auth-context'
import { AuthClient } from './infrastructure/auth-client'

const authClient = new AuthClient()

export function AuthProvider({ children }: { children: ReactNode }) {
  const snapshot = useSyncExternalStore(authClient.subscribe, authClient.getSnapshot, authClient.getSnapshot)

  useEffect(() => {
    void authClient.refreshSession()
    const refreshVisibleSession = () => {
      if (document.visibilityState === 'visible') {
        void authClient.refreshSession()
      }
    }
    window.addEventListener('focus', refreshVisibleSession)
    document.addEventListener('visibilitychange', refreshVisibleSession)
    return () => {
      window.removeEventListener('focus', refreshVisibleSession)
      document.removeEventListener('visibilitychange', refreshVisibleSession)
    }
  }, [])

  const value = useMemo(
    () => ({
      ...snapshot,
      ensureSession: authClient.ensureSession,
      refreshSession: authClient.refreshSession,
      startOAuth: authClient.startOAuth,
      passwordLogin: authClient.passwordLogin,
      authenticatedRequest: authClient.authenticatedRequest,
      logout: authClient.logout,
    }),
    [snapshot],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
