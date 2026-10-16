import i18next, { type TFunction } from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import { APP_LANGUAGES, DEFAULT_APP_LANGUAGE, LANGUAGE_STORAGE_KEY, resolveAppLanguage } from './model/language'
import { resources } from './resources'

export const i18n = i18next.createInstance()

const languageDetector = new LanguageDetector()
languageDetector.addDetector({
  name: 'appStorage',
  lookup() {
    try {
      return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) ?? undefined
    } catch {
      return undefined
    }
  },
  cacheUserLanguage(language) {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
    } catch {
      // Keep language switching available when storage is blocked or full.
    }
  },
})

let initialization: Promise<TFunction> | undefined

export function initializeI18n(): Promise<TFunction> {
  initialization ??= i18n
    .use(languageDetector)
    .use(initReactI18next)
    .init({
      resources,
      supportedLngs: [...APP_LANGUAGES],
      fallbackLng: DEFAULT_APP_LANGUAGE,
      defaultNS: 'common',
      ns: ['common', 'navigation', 'theme', 'pages', 'auth'],
      load: 'currentOnly',
      returnNull: false,
      interpolation: {
        escapeValue: false,
      },
      detection: {
        order: ['appStorage', 'navigator'],
        caches: ['appStorage'],
        convertDetectedLanguage: resolveAppLanguage,
      },
    })

  return initialization
}
