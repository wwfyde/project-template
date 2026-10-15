import type { ResolvedThemeMode, ThemeMode, ThemePreferences } from '../model/theme-config'

export function getSystemTheme(): ResolvedThemeMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function resolveThemeMode(mode: ThemeMode, systemTheme = getSystemTheme()): ResolvedThemeMode {
  return mode === 'system' ? systemTheme : mode
}

function setOptionalDataAttribute(element: HTMLElement, name: string, value: string, defaultValue: string) {
  if (value === defaultValue) {
    delete element.dataset[name]
    return
  }

  element.dataset[name] = value
}

export function applyThemeToDocument(preferences: ThemePreferences, resolvedMode = resolveThemeMode(preferences.mode)) {
  if (typeof document === 'undefined') return

  const root = document.documentElement

  root.classList.remove('light', 'dark')
  root.classList.add(resolvedMode)
  root.style.colorScheme = resolvedMode
  root.dataset.themeMode = preferences.mode

  // Keep inputs and derived CSS variables on the same element so presets update every token.
  setOptionalDataAttribute(root, 'themePreset', preferences.preset, 'default')
  setOptionalDataAttribute(root, 'themeRadius', preferences.radius, 'default')
  setOptionalDataAttribute(root, 'themeDensity', preferences.density, 'default')
  root.dataset.themeContentWidth = preferences.contentWidth
  root.dataset.themeReady = 'true'
}

export function subscribeToSystemTheme(onChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => undefined

  const media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}
