import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/assets/')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation('pages')

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-6 text-card-foreground">
      <h1 className="text-2xl font-semibold">{t('assetsTitle')}</h1>
      <p className="text-muted-foreground">{t('assetsGreeting')}</p>
    </section>
  )
}
