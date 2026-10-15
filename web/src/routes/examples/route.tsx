import { createFileRoute, Link, Outlet } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/examples')({
  component: ExampleLayout,
})

function ExampleLayout() {
  const { t } = useTranslation('navigation')
  const linkClassName =
    'rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&.active]:bg-primary [&.active]:text-primary-foreground'

  return (
    <div className="space-y-6">
      <nav aria-label={t('examplesLabel')} className="flex flex-wrap gap-2 border-b border-border pb-4">
        <Link to="/examples" activeOptions={{ exact: true }} className={linkClassName}>
          {t('overview')}
        </Link>
        <Link to="/examples/radix" activeOptions={{ exact: true }} className={linkClassName}>
          {t('radix')}
        </Link>
        <Link to="/examples/radix/theme" className={linkClassName}>
          {t('radixTheme')}
        </Link>
      </nav>
      <Outlet />
    </div>
  )
}
