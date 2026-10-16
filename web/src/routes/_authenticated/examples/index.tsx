import { Button, Flex, Text } from '@radix-ui/themes'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

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
      <Flex direction="column" gap="4" align="start">
        <Text>{t('radixGreeting')}</Text>
        <Button className="theme-radix-button" onClick={() => setCount((value) => value + 1)}>
          {t('radixAction')}
        </Button>
        <Text size="2" className="text-muted-foreground" aria-live="polite">
          {t('clickCount', { count })}
        </Text>
      </Flex>
    </section>
  )
}
