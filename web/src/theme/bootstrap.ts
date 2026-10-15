import { applyThemeToDocument } from './infrastructure/theme-document'
import { createLocalThemeStorage } from './infrastructure/theme-storage'
import { DEFAULT_THEME_PREFERENCES } from './model/theme-config'

export function initializeTheme() {
  const preferences = createLocalThemeStorage().read() ?? DEFAULT_THEME_PREFERENCES
  applyThemeToDocument(preferences)
}
