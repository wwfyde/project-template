import { describe, expect, it } from 'vitest'

import { DEFAULT_THEME_PREFERENCES, THEME_PRESETS } from './theme-config'
import {
  isDefaultThemePreferences,
  mergeThemePreferences,
  normalizeThemePreferences,
  parseStoredTheme,
  serializeStoredTheme,
} from './theme-preferences'

describe('theme preferences', () => {
  it('falls back per field when persisted data contains unsupported values', () => {
    expect(
      normalizeThemePreferences({
        mode: 'dark',
        preset: 'future-preset',
        radius: null,
        density: 'compact',
        contentWidth: 'centered',
      }),
    ).toEqual({
      ...DEFAULT_THEME_PREFERENCES,
      mode: 'dark',
      density: 'compact',
      contentWidth: 'centered',
    })
  })

  it.each(THEME_PRESETS)('persists $value independently of mode and layout preferences', ({ value: preset }) => {
    const preferences = mergeThemePreferences(DEFAULT_THEME_PREFERENCES, {
      mode: 'dark',
      preset,
      radius: 'sm',
    })

    expect(parseStoredTheme(serializeStoredTheme(preferences))).toEqual(preferences)
  })

  it('ignores malformed and future storage versions', () => {
    expect(parseStoredTheme('{')).toBeUndefined()
    expect(parseStoredTheme(JSON.stringify({ version: 2, preferences: {} }))).toBeUndefined()
  })

  it('detects whether preferences are the defaults', () => {
    expect(isDefaultThemePreferences({ ...DEFAULT_THEME_PREFERENCES })).toBe(true)
    expect(isDefaultThemePreferences({ ...DEFAULT_THEME_PREFERENCES, mode: 'dark' })).toBe(false)
  })
})
