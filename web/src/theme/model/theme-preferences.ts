import {
  CONTENT_WIDTHS,
  DEFAULT_THEME_PREFERENCES,
  THEME_DENSITIES,
  THEME_MODES,
  THEME_PRESETS,
  THEME_RADII,
  type ThemePreferences,
} from './theme-config'

const allowedValues = {
  mode: new Set(THEME_MODES.map((option) => option.value)),
  preset: new Set(THEME_PRESETS.map((option) => option.value)),
  radius: new Set(THEME_RADII.map((option) => option.value)),
  density: new Set(THEME_DENSITIES.map((option) => option.value)),
  contentWidth: new Set(CONTENT_WIDTHS.map((option) => option.value)),
}

type StoredTheme = {
  version: 1
  preferences: ThemePreferences
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function allowed<T extends string>(set: ReadonlySet<T>, value: unknown, fallback: T): T {
  return typeof value === 'string' && set.has(value as T) ? (value as T) : fallback
}

export function normalizeThemePreferences(value: unknown): ThemePreferences {
  const input = isRecord(value) ? value : {}

  return {
    mode: allowed(allowedValues.mode, input.mode, DEFAULT_THEME_PREFERENCES.mode),
    preset: allowed(allowedValues.preset, input.preset, DEFAULT_THEME_PREFERENCES.preset),
    radius: allowed(allowedValues.radius, input.radius, DEFAULT_THEME_PREFERENCES.radius),
    density: allowed(allowedValues.density, input.density, DEFAULT_THEME_PREFERENCES.density),
    contentWidth: allowed(allowedValues.contentWidth, input.contentWidth, DEFAULT_THEME_PREFERENCES.contentWidth),
  }
}

export function mergeThemePreferences(current: ThemePreferences, patch: Partial<ThemePreferences>): ThemePreferences {
  return normalizeThemePreferences({ ...current, ...patch })
}

export function parseStoredTheme(value: string | null): ThemePreferences | undefined {
  if (!value) return undefined

  try {
    const stored = JSON.parse(value) as unknown
    if (!isRecord(stored) || stored.version !== 1 || !('preferences' in stored)) return undefined
    return normalizeThemePreferences(stored.preferences)
  } catch {
    return undefined
  }
}

export function serializeStoredTheme(preferences: ThemePreferences): string {
  const stored: StoredTheme = { version: 1, preferences: normalizeThemePreferences(preferences) }
  return JSON.stringify(stored)
}

export function isDefaultThemePreferences(preferences: ThemePreferences): boolean {
  return Object.entries(DEFAULT_THEME_PREFERENCES).every(
    ([key, value]) => preferences[key as keyof ThemePreferences] === value,
  )
}
