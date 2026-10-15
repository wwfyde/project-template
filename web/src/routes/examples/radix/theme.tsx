import { Button, Flex, Text } from '@radix-ui/themes'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/examples/radix/theme')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation('pages')
  const [count, setCount] = useState(0)

  return (
    <section className="space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t('radixThemeTitle')}</h1>
        <p className="text-muted-foreground">{t('radixThemeDescription')}</p>
      </header>
      <Flex direction="column" gap="4" align="start">
        <Text>{t('radixGreeting')}</Text>
        <Flex gap="3" wrap="wrap">
          <Button className="theme-radix-button" onClick={() => setCount((value) => value + 1)}>
            {t('radixAction')}
          </Button>
          <Button
            className="theme-radix-button theme-radix-button-outline"
            variant="outline"
            disabled={count === 0}
            onClick={() => setCount(0)}
          >
            {t('reset')}
          </Button>
        </Flex>
        <Text size="2" className="text-muted-foreground" aria-live="polite">
          {t('clickCount', { count })}
        </Text>
      </Flex>
    </section>
  )
}
