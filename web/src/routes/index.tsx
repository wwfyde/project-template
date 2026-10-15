import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/')({
  component: Index,
})

function Index() {
  const { t } = useTranslation('pages')
  const [count, setCount] = useState(0)
  const [title, setTitle] = useState('')

  return (
    <div className="space-y-8">
      <header className="max-w-2xl space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">{t('greeting')}</h1>
        <p className="text-base leading-relaxed text-muted-foreground">{t('homeDescription')}</p>
      </header>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
          <span className="inline-flex rounded-md bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">
            {t('previewBadge')}
          </span>
          <div className="space-y-2">
            <h2 className="break-words text-2xl font-semibold">{title.trim() || t('previewTitle')}</h2>
            <p className="text-sm leading-relaxed text-muted-foreground">{t('previewDescription')}</p>
          </div>
          <div className="space-y-2">
            <label htmlFor="preview-title" className="block text-sm font-medium">
              {t('previewLabel')}
            </label>
            <input
              id="preview-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t('previewPlaceholder')}
              aria-describedby="preview-title-hint"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            />
            <p id="preview-title-hint" className="text-xs text-muted-foreground">
              {t('previewHint')}
            </p>
          </div>
        </section>
        <section className="flex flex-col gap-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold">{t('interactionTitle')}</h2>
            <p className="text-sm leading-relaxed text-muted-foreground">{t('interactionDescription')}</p>
          </div>
          <div className="flex flex-1 items-center justify-center rounded-md bg-muted p-8 text-center">
            <p aria-live="polite" className="text-xl font-medium text-foreground">
              {t('clickCount', { count })}
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setCount((value) => value + 1)}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {t('increment')}
            </button>
            <button
              type="button"
              onClick={() => setCount(0)}
              disabled={count === 0}
              className="rounded-md border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-secondary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('reset')}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
