import { Theme as RadixTheme } from '@radix-ui/themes'
import type { ReactNode } from 'react'

import { AuthProvider } from '../features/auth'
import { I18nProvider } from '../i18n'
import { ThemeProvider, useTheme } from '../theme'

function ComponentTheme({ children }: { children: ReactNode }) {
  const { preferences, resolvedMode } = useTheme()
  const scaling = { compact: '90%', default: '100%', comfortable: '110%' } as const

  return (
    <RadixTheme
      appearance={resolvedMode}
      hasBackground={false}
      scaling={scaling[preferences.density]}
      className="app-radix-theme"
    >
      {children}
    </RadixTheme>
  )
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <ThemeProvider>
        <ComponentTheme>
          <AuthProvider>{children}</AuthProvider>
        </ComponentTheme>
      </ThemeProvider>
    </I18nProvider>
  )
}
