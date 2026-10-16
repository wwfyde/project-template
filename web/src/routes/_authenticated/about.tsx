import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/_authenticated/about')({
  component: AboutComponent,
})

function AboutComponent() {
  const { t } = useTranslation('pages')
  const [count, setCount] = useState(0)
  const [showMessage, setShowMessage] = useState(false)

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">{t('aboutTitle')}</h1>
        <p className="text-muted-foreground">{t('aboutDescription')}</p>
      </header>
      <section className="max-w-xl space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
        <div className="flex flex-col items-start gap-6 md:flex-row md:items-center">
          <img src="/avatar.jpg" className="h-24 w-24 shrink-0 rounded-full object-cover" alt={t('profileAvatar')} />
          <div className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold">{t('profileName')}</h2>
              <p className="text-sm text-muted-foreground">{t('profileRole')}</p>
            </div>
            <button
              type="button"
              onClick={() => setShowMessage((value) => !value)}
              aria-expanded={showMessage}
              aria-controls="profile-message"
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {t('sendMessage')}
            </button>
          </div>
        </div>
        {showMessage && (
          <p id="profile-message" className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
            {t('profilePreview')}
          </p>
        )}
        <div className="border-t border-border pt-6">
          <button
            type="button"
            onClick={() => setCount((value) => value + 1)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {t('clickCount', { count })}
          </button>
        </div>
      </section>
    </div>
  )
}
