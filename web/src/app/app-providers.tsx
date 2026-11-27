import type { ReactNode } from 'react'

import { AuthProvider } from '../features/auth'
import { I18nProvider } from '../i18n'
import { ThemeProvider } from '../theme'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <ThemeProvider>
        <AuthProvider>{children}</AuthProvider>
      </ThemeProvider>
    </I18nProvider>
  )
}
