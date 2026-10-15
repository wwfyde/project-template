import { Button, Flex, Text } from '@radix-ui/themes'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/examples/radix/')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation(['pages', 'navigation'])

  return (
    <section className="space-y-6 rounded-lg border border-border bg-card p-6 text-card-foreground">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t('radixTitle')}</h1>
        <p className="text-muted-foreground">{t('radixDescription')}</p>
      </header>
      <Flex direction="column" gap="4" align="start">
        <Text>{t('radixGreeting')}</Text>
        <Button asChild className="theme-radix-button">
          <Link to="/examples/radix/theme">{t('radixTheme', { ns: 'navigation' })}</Link>
        </Button>
      </Flex>
    </section>
  )
}
