import { ChevronDown, Languages } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { APP_LANGUAGES, resolveAppLanguage, type AppLanguage } from '../model/language'

const languageLabelKeys = {
  en: 'languages.en',
  'zh-CN': 'languages.zhCN',
} as const satisfies Record<AppLanguage, 'languages.en' | 'languages.zhCN'>

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { i18n, t } = useTranslation('common')
  const language = resolveAppLanguage(i18n.resolvedLanguage)

  return (
    <label
      className={`relative inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-border bg-card text-foreground shadow-sm transition hover:bg-accent focus-within:ring-2 focus-within:ring-ring ${compact ? 'size-11 justify-center md:h-9 md:w-auto md:justify-start md:px-2.5' : 'h-11 px-3 md:h-9'}`}
    >
      <Languages className="size-4 shrink-0" aria-hidden="true" />
      <span className="sr-only">{t('languageSwitcherLabel')}</span>
      <select
        value={language}
        onChange={(event) => void i18n.changeLanguage(event.target.value)}
        className={
          compact
            ? 'absolute inset-0 size-full cursor-pointer opacity-0 md:static md:size-auto md:appearance-none md:bg-transparent md:pr-4 md:text-xs md:font-medium md:opacity-100 md:outline-none'
            : 'cursor-pointer appearance-none bg-transparent pr-4 text-sm font-medium outline-none md:text-xs'
        }
        aria-label={t('languageSwitcherLabel')}
      >
        {APP_LANGUAGES.map((option) => (
          <option key={option} value={option}>
            {t(languageLabelKeys[option])}
          </option>
        ))}
      </select>
      <ChevronDown
        className={`pointer-events-none absolute right-2 size-3.5 text-muted-foreground ${compact ? 'hidden md:block' : ''}`}
        aria-hidden="true"
      />
    </label>
  )
}
