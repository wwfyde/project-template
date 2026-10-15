import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_THEME_PREFERENCES } from '../model/theme-config'
import { applyThemeToDocument, getSystemTheme, resolveThemeMode, subscribeToSystemTheme } from './theme-document'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('theme document', () => {
  it('applies preferences to the html root and clears optional attributes on reset', () => {
    const classes = new Set(['light', 'app-root'])
    const root = {
      dataset: {} as Record<string, string>,
      style: { colorScheme: '' },
      classList: {
        add: (...names: string[]) => names.forEach((name) => classes.add(name)),
        remove: (...names: string[]) => names.forEach((name) => classes.delete(name)),
      },
    }
    vi.stubGlobal('document', { documentElement: root })

    applyThemeToDocument(
      {
        mode: 'system',
        preset: 'ocean-breeze',
        radius: 'sm',
        density: 'compact',
        contentWidth: 'centered',
      },
      'dark',
    )

    expect(classes).toEqual(new Set(['app-root', 'dark']))
    expect(root.style.colorScheme).toBe('dark')
    expect(root.dataset).toEqual({
      themeMode: 'system',
      themePreset: 'ocean-breeze',
      themeRadius: 'sm',
      themeDensity: 'compact',
      themeContentWidth: 'centered',
      themeReady: 'true',
    })

    applyThemeToDocument(DEFAULT_THEME_PREFERENCES, 'light')

    expect(classes).toEqual(new Set(['app-root', 'light']))
    expect(root.style.colorScheme).toBe('light')
    expect(root.dataset).toEqual({
      themeMode: 'system',
      themeContentWidth: 'full',
      themeReady: 'true',
    })
  })

  it('follows system preference changes until the listener is removed', () => {
    const events = new EventTarget()
    const media = {
      matches: true,
      addEventListener: events.addEventListener.bind(events),
      removeEventListener: events.removeEventListener.bind(events),
    }
    const matchMedia = vi.fn(() => media)
    vi.stubGlobal('window', { matchMedia })

    expect(getSystemTheme()).toBe('dark')
    expect(resolveThemeMode('system')).toBe('dark')
    expect(resolveThemeMode('light')).toBe('light')
    expect(matchMedia).toHaveBeenCalledWith('(prefers-color-scheme: dark)')

    const onChange = vi.fn(() => resolveThemeMode('system'))
    const unsubscribe = subscribeToSystemTheme(onChange)
    media.matches = false
    events.dispatchEvent(new Event('change'))

    expect(onChange).toHaveBeenCalledOnce()
    expect(onChange).toHaveReturnedWith('light')

    unsubscribe()
    events.dispatchEvent(new Event('change'))
    expect(onChange).toHaveBeenCalledOnce()
  })

  it('can bootstrap without browser APIs', () => {
    vi.stubGlobal('window', undefined)
    vi.stubGlobal('document', undefined)

    expect(getSystemTheme()).toBe('light')
    expect(() => applyThemeToDocument(DEFAULT_THEME_PREFERENCES)).not.toThrow()
    expect(() => subscribeToSystemTheme(vi.fn())()).not.toThrow()

    vi.stubGlobal('window', {})
    expect(getSystemTheme()).toBe('light')
    expect(() => subscribeToSystemTheme(vi.fn())()).not.toThrow()
  })
})
