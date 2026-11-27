// @vitest-environment jsdom

import { act, createElement, useLayoutEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { initializeTheme } from './bootstrap'
import { THEME_STORAGE_KEY } from './model/theme-config'
import { ThemeProvider } from './theme-provider'
import { useTheme } from './use-theme'

let root: Root
let container: HTMLDivElement
let theme: ReturnType<typeof useTheme>

function Probe() {
  const value = useTheme()
  useLayoutEffect(() => {
    theme = value
  })
  return null
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  localStorage.clear()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  localStorage.clear()
  document.documentElement.removeAttribute('class')
  document.documentElement.removeAttribute('style')
  for (const key of Object.keys(document.documentElement.dataset)) {
    delete document.documentElement.dataset[key]
  }
  vi.unstubAllGlobals()
})

async function mountProvider() {
  await act(async () => root.render(createElement(ThemeProvider, null, createElement(Probe))))
}

describe('theme provider', () => {
  it('keeps the selected style through system changes, manual mode, bootstrap, and reset', async () => {
    const events = new EventTarget()
    const media = {
      matches: false,
      addEventListener: events.addEventListener.bind(events),
      removeEventListener: events.removeEventListener.bind(events),
    }
    vi.stubGlobal('matchMedia', () => media)

    await mountProvider()
    expect(document.documentElement.dataset.themePreset).toBe('chatgpt')
    expect(theme.resolvedMode).toBe('light')

    await act(async () => theme.setPreferences({ preset: 'apple-ios26' }))
    await act(async () => {
      media.matches = true
      events.dispatchEvent(new Event('change'))
    })
    expect(theme.preferences.mode).toBe('system')
    expect(theme.preferences.preset).toBe('apple-ios26')
    expect(theme.resolvedMode).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    await act(async () => theme.setPreferences({ mode: 'light', preset: 'wechat' }))
    await act(async () => events.dispatchEvent(new Event('change')))
    expect(theme.resolvedMode).toBe('light')
    expect(document.documentElement.dataset.themePreset).toBe('wechat')
    expect(JSON.parse(localStorage.getItem(THEME_STORAGE_KEY)!)).toMatchObject({
      preferences: { mode: 'light', preset: 'wechat' },
    })

    await act(async () => root.unmount())
    root = createRoot(container)
    document.documentElement.dataset.themePreset = ''
    initializeTheme()
    expect(document.documentElement.dataset.themePreset).toBe('wechat')
    expect(document.documentElement.style.colorScheme).toBe('light')
    await mountProvider()
    expect(theme.preferences).toMatchObject({ mode: 'light', preset: 'wechat' })

    await act(async () => theme.resetPreferences())
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
    expect(document.documentElement.dataset.themePreset).toBe('chatgpt')
    expect(theme.preferences.mode).toBe('system')
    expect(theme.resolvedMode).toBe('dark')
  })
})
