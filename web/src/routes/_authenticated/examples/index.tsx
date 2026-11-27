import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../../components/ui/button'

export const Route = createFileRoute('/_authenticated/examples/')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation('pages')
  const [count, setCount] = useState(0)

  return (
    <section className="space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t('examplesTitle')}</h1>
        <p className="text-muted-foreground">{t('examplesDescription')}</p>
      </header>
      <p>{t('exampleGreeting', { resource: t('asset') })}</p>
      <div className="flex flex-col items-start gap-4">
        <p>{t('baseUiGreeting')}</p>
        <Button onClick={() => setCount((value) => value + 1)}>{t('baseUiAction')}</Button>
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {t('clickCount', { count })}
        </p>
      </div>
    </section>
  )
}
