import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { useTranslation } from 'react-i18next'

import { LanguageSwitcher } from '../i18n'
import { ThemeConfigurator } from '../theme'

function RootLayout() {
  const { t } = useTranslation(['navigation', 'common'])
  const links = [
    { to: '/', label: 'home' },
    { to: '/admin', label: 'admin' },
    { to: '/assets', label: 'assets' },
    { to: '/examples', label: 'examples' },
    { to: '/about', label: 'about' },
  ] as const

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b border-border bg-card text-card-foreground">
        <div className="app-content flex flex-wrap items-center gap-3 px-4 py-3 md:px-8">
          <Link to="/" className="mr-auto font-semibold tracking-tight">
            {t('appName', { ns: 'common' })}
          </Link>
          <nav
            aria-label={t('primaryLabel')}
            className="order-last flex w-full flex-wrap gap-1 md:order-none md:w-auto"
          >
            {links.map(({ to, label }) => (
              <Link
                key={to}
                to={to}
                activeOptions={{ exact: to === '/' }}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&.active]:bg-accent [&.active]:font-medium [&.active]:text-accent-foreground"
              >
                {t(label)}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <LanguageSwitcher compact />
            <ThemeConfigurator />
          </div>
        </div>
      </header>
      <main className="app-content px-4 py-8 md:px-8 md:py-10">
        <Outlet />
      </main>
      {import.meta.env.DEV ? <TanStackRouterDevtools /> : null}
    </div>
  )
}

export const Route = createRootRoute({ component: RootLayout })
