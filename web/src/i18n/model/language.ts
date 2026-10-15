export const APP_LANGUAGES = ['zh-CN', 'en'] as const

export type AppLanguage = (typeof APP_LANGUAGES)[number]

export const DEFAULT_APP_LANGUAGE: AppLanguage = 'en'
export const LANGUAGE_STORAGE_KEY = 'project-template.language.v1'

export function resolveAppLanguage(language?: string | null): AppLanguage {
  if (language?.toLowerCase().startsWith('zh')) {
    return 'zh-CN'
  }

  return 'en'
}
