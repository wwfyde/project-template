import { Link, Navigate, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { LogOut } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { normalizeReturnTo, useAuth } from '../../features/auth'
import { LanguageSwitcher } from '../../i18n'
import { ThemeConfigurator } from '../../theme'

export function AuthenticatedShell() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const { t } = useTranslation(['navigation', 'common', 'auth'])
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutFailed, setLogoutFailed] = useState(false)
  const links = [
    { to: '/', label: 'home' },
    { to: '/admin', label: 'admin' },
    { to: '/assets', label: 'assets' },
    { to: '/examples', label: 'examples' },
    { to: '/about', label: 'about' },
    { to: '/account', label: 'account' },
  ] as const

  const handleLogout = async () => {
    setIsLoggingOut(true)
    setLogoutFailed(false)
    try {
      await auth.logout()
      await navigate({ to: '/login', search: { redirect: '/' }, replace: true })
    } catch {
      setLogoutFailed(true)
    } finally {
      setIsLoggingOut(false)
    }
  }

  if (auth.status !== 'authenticated') {
    return <Navigate to="/login" search={{ redirect: normalizeReturnTo(location.href) }} replace />
  }

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
          <Link
            to="/account"
            className="hidden max-w-40 truncate rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:block"
          >
            {auth.user?.display_name}
          </Link>
          <div className="flex items-center gap-2">
            <LanguageSwitcher compact />
            <ThemeConfigurator />
            <button
              type="button"
              onClick={() => void handleLogout()}
              disabled={isLoggingOut}
              aria-label={t('logout', { ns: 'auth' })}
              title={t('logout', { ns: 'auth' })}
              className="inline-flex size-9 items-center justify-center rounded-md border border-border bg-background transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-50"
            >
              <LogOut className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>
      <main className="app-content px-4 py-8 md:px-8 md:py-10">
        {logoutFailed ? (
          <p
            role="alert"
            className="mb-6 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive"
          >
            {t('errors.logoutFailed', { ns: 'auth' })}
          </p>
        ) : null}
        <Outlet />
      </main>
    </div>
  )
}
