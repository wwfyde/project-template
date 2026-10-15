import { useEffect, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'

import { i18n } from './config'
import { resolveAppLanguage } from './model/language'

type I18nProviderProps = {
  children: ReactNode
}

export function I18nProvider({ children }: I18nProviderProps) {
  useEffect(() => {
    const syncDocumentLanguage = (language: string) => {
      document.documentElement.lang = resolveAppLanguage(language)
    }

    syncDocumentLanguage(i18n.resolvedLanguage ?? i18n.language)
    i18n.on('languageChanged', syncDocumentLanguage)

    return () => {
      i18n.off('languageChanged', syncDocumentLanguage)
    }
  }, [])

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
}
