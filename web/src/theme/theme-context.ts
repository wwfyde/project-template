import { createContext } from 'react'

import type { ResolvedThemeMode, ThemePreferences } from './model/theme-config'

export type ThemeContextValue = {
  preferences: ThemePreferences
  resolvedMode: ResolvedThemeMode
  setPreferences: (patch: Partial<ThemePreferences>) => void
  resetPreferences: () => void
}

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)
