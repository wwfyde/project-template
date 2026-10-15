import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  applyThemeToDocument,
  getSystemTheme,
  resolveThemeMode,
  subscribeToSystemTheme,
} from './infrastructure/theme-document'
import { createLocalThemeStorage, type ThemeStorage } from './infrastructure/theme-storage'
import { DEFAULT_THEME_PREFERENCES, type ResolvedThemeMode, type ThemePreferences } from './model/theme-config'
import { isDefaultThemePreferences, mergeThemePreferences } from './model/theme-preferences'
import { ThemeContext } from './theme-context'

type ThemeProviderProps = {
  children: ReactNode
  storage?: ThemeStorage
}

export function ThemeProvider({ children, storage: storageOverride }: ThemeProviderProps) {
  const storage = useMemo(() => storageOverride ?? createLocalThemeStorage(), [storageOverride])
  const [preferences, setPreferencesState] = useState<ThemePreferences>(
    () => storage.read() ?? DEFAULT_THEME_PREFERENCES,
  )
  const [resolvedMode, setResolvedMode] = useState<ResolvedThemeMode>(() => resolveThemeMode(preferences.mode))

  useEffect(() => {
    if (isDefaultThemePreferences(preferences)) storage.clear()
    else storage.write(preferences)
  }, [preferences, storage])

  useEffect(() => {
    const apply = () => {
      const nextMode = resolveThemeMode(preferences.mode, getSystemTheme())
      setResolvedMode(nextMode)
      applyThemeToDocument(preferences, nextMode)
    }

    apply()
    if (preferences.mode !== 'system') return undefined
    return subscribeToSystemTheme(apply)
  }, [preferences])

  const setPreferences = useCallback((patch: Partial<ThemePreferences>) => {
    setPreferencesState((current) => mergeThemePreferences(current, patch))
  }, [])

  const resetPreferences = useCallback(() => {
    setPreferencesState({ ...DEFAULT_THEME_PREFERENCES })
  }, [])

  const value = useMemo(
    () => ({ preferences, resolvedMode, setPreferences, resetPreferences }),
    [preferences, resolvedMode, resetPreferences, setPreferences],
  )

  return <ThemeContext value={value}>{children}</ThemeContext>
}
