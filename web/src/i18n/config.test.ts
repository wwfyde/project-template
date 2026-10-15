import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LANGUAGE_STORAGE_KEY } from './model/language'

let values: Map<string, string>

beforeEach(() => {
  vi.resetModules()
  values = new Map()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
  vi.stubGlobal('navigator', { languages: ['en-US'], language: 'en-US' })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('i18n initialization', () => {
  it('initializes once and prefers a saved language over the browser language', async () => {
    values.set(LANGUAGE_STORAGE_KEY, 'zh-CN')
    const { i18n, initializeI18n } = await import('./config')
    const initialization = initializeI18n()

    expect(initializeI18n()).toBe(initialization)
    await initialization

    expect(i18n.resolvedLanguage).toBe('zh-CN')
    expect(i18n.t('home', { ns: 'navigation' })).toBe('首页')
  })

  it('switches and persists language with correct interpolation and plural forms', async () => {
    const { i18n, initializeI18n } = await import('./config')
    await initializeI18n()

    expect(i18n.resolvedLanguage).toBe('en')
    expect(i18n.t('clickCount', { ns: 'pages', count: 1 })).toBe('Clicked 1 time')
    expect(i18n.t('clickCount', { ns: 'pages', count: 2 })).toBe('Clicked 2 times')

    await i18n.changeLanguage('zh-CN')
    expect(i18n.t('clickCount', { ns: 'pages', count: 1 })).toBe('已点击 1 次')
    expect(i18n.t('clickCount', { ns: 'pages', count: 2 })).toBe('已点击 2 次')
    expect(values.get(LANGUAGE_STORAGE_KEY)).toBe('zh-CN')

    await i18n.changeLanguage('en')
    expect(i18n.t('home', { ns: 'navigation' })).toBe('Home')
    expect(values.get(LANGUAGE_STORAGE_KEY)).toBe('en')
  })

  it('uses the browser language when storage access is denied', async () => {
    vi.stubGlobal('window', {
      get localStorage() {
        throw new Error('Storage access denied')
      },
    })
    vi.stubGlobal('navigator', { languages: ['zh-HK'], language: 'zh-HK' })
    const { i18n, initializeI18n } = await import('./config')

    await initializeI18n()

    expect(i18n.resolvedLanguage).toBe('zh-CN')
    await expect(i18n.changeLanguage('en')).resolves.toBeTypeOf('function')
    expect(i18n.t('home', { ns: 'navigation' })).toBe('Home')
  })
})
