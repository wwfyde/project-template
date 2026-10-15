import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_THEME_PREFERENCES, THEME_STORAGE_KEY } from '../model/theme-config'
import { createLocalThemeStorage } from './theme-storage'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('local theme storage', () => {
  it('persists preferences under the app key and removes them on clear', () => {
    const values = new Map<string, string>()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    })
    const storage = createLocalThemeStorage()
    const preferences = { ...DEFAULT_THEME_PREFERENCES, mode: 'dark' as const }

    expect(storage.read()).toBeUndefined()
    storage.write(preferences)
    expect(JSON.parse(values.get(THEME_STORAGE_KEY)!)).toEqual({ version: 1, preferences })
    expect(storage.read()).toEqual(preferences)

    storage.clear()
    expect(values.has(THEME_STORAGE_KEY)).toBe(false)
    expect(storage.read()).toBeUndefined()
  })

  it('ignores malformed saved data', () => {
    vi.stubGlobal('window', { localStorage: { getItem: () => '{invalid' } })

    expect(createLocalThemeStorage().read()).toBeUndefined()
  })

  it('keeps storage failures from interrupting theme changes', () => {
    vi.stubGlobal('window', {
      get localStorage() {
        throw new Error('Storage access denied')
      },
    })
    const storage = createLocalThemeStorage()

    expect(storage.read()).toBeUndefined()
    expect(() => storage.write(DEFAULT_THEME_PREFERENCES)).not.toThrow()
    expect(() => storage.clear()).not.toThrow()
  })
})
