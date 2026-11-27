import { createFileRoute, Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/_authenticated/examples/base-ui/')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation(['pages', 'navigation'])

  return (
    <section className="space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t('baseUiTitle')}</h1>
        <p className="text-muted-foreground">{t('baseUiDescription')}</p>
      </header>
      <div className="flex flex-col items-start gap-4">
        <p>{t('baseUiGreeting')}</p>
        <Link
          to="/examples/base-ui/theme"
          className="inline-flex min-h-9 items-center justify-center rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none"
        >
          {t('baseUiTheme', { ns: 'navigation' })}
        </Link>
      </div>
    </section>
  )
}
