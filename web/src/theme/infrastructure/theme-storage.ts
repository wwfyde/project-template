import { THEME_STORAGE_KEY, type ThemePreferences } from '../model/theme-config'
import { parseStoredTheme, serializeStoredTheme } from '../model/theme-preferences'

export type ThemeStorage = {
  read: () => ThemePreferences | undefined
  write: (preferences: ThemePreferences) => void
  clear: () => void
}

export function createLocalThemeStorage(key = THEME_STORAGE_KEY): ThemeStorage {
  return {
    read() {
      if (typeof window === 'undefined') return undefined

      try {
        return parseStoredTheme(window.localStorage.getItem(key))
      } catch {
        return undefined
      }
    },
    write(preferences) {
      if (typeof window === 'undefined') return

      try {
        window.localStorage.setItem(key, serializeStoredTheme(preferences))
      } catch {
        // Storage can be unavailable in private or policy-restricted contexts.
      }
    },
    clear() {
      if (typeof window === 'undefined') return

      try {
        window.localStorage.removeItem(key)
      } catch {
        // Keep the active in-memory theme when persistence is unavailable.
      }
    },
  }
}
