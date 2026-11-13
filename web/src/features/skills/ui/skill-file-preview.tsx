import { useTranslation } from 'react-i18next'

import { formatSkillBytes, type SkillFileData } from '../model/skill'
import './skills.css'

export type SkillFilePreviewProps = {
  file: SkillFileData | null
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

/** File contents always remain escaped text, including Markdown, HTML and SVG. */
export function SkillFilePreview({ file, loading = false, error, onRetry }: SkillFilePreviewProps) {
  const { t } = useTranslation('skills')
  return (
    <section className="skill-file-preview" aria-label={t('filePreview')} aria-busy={loading}>
      {loading ? (
        <p role="status" className="p-5 text-sm text-muted-foreground">
          {t('loading')}
        </p>
      ) : error ? (
        <div role="alert" className="skill-error m-4 space-y-3">
          <p>{error}</p>
          {onRetry && (
            <button type="button" className="skill-button" onClick={onRetry}>
              {t('retry')}
            </button>
          )}
        </div>
      ) : !file ? (
        <p className="p-5 text-sm text-muted-foreground">{t('selectFile')}</p>
      ) : (
        <>
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-3 text-xs">
            <span className="min-w-0 break-all font-mono">{file.path}</span>
            <span className="text-muted-foreground">
              {formatSkillBytes(file.size)} · {file.media_type}
            </span>
          </header>
          {file.truncated && (
            <p role="status" className="border-b border-border bg-muted p-3 text-sm">
              {t('truncated')}
            </p>
          )}
          {file.content === null ? (
            <p className="p-5 text-sm text-muted-foreground">{t('binaryPreview')}</p>
          ) : (
            <pre tabIndex={0} aria-label={t('sourcePreview')} className="skill-source">
              <code>{file.content}</code>
            </pre>
          )}
        </>
      )}
    </section>
  )
}
