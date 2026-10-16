import { useRouter, useSearch } from '@tanstack/react-router'
import { ArrowRight, Building2, Globe, LoaderCircle, ShieldCheck, Smartphone } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { LanguageSwitcher } from '../../../i18n'
import { ThemeConfigurator } from '../../../theme'
import type { AuthProviderSummary } from '../model/auth'
import { useAuth } from '../use-auth'

export function LoginPage() {
  const auth = useAuth()
  const router = useRouter()
  const search = useSearch({ from: '/login' })
  const { t } = useTranslation(['auth', 'common'])
  const [providerError, setProviderError] = useState(false)
  const [isRetrying, setIsRetrying] = useState(false)
  const [isSigningIn, setIsSigningIn] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState(false)
  const availableProviders = auth.providers.filter((provider) => provider.enabled)
  const passwordProvider = availableProviders.find(
    (provider) => provider.id === 'password' && provider.method === 'password',
  )
  const hasLoginProvider = availableProviders.some(
    (provider) =>
      provider.implemented &&
      ((provider.method === 'oauth' && provider.start_path) ||
        (provider.id === 'password' && provider.method === 'password')),
  )

  useEffect(() => {
    if (auth.status === 'authenticated') {
      router.history.replace(search.redirect)
    }
  }, [auth.status, router, search.redirect])

  const startOAuth = (provider: AuthProviderSummary) => {
    setProviderError(false)
    try {
      auth.startOAuth(provider.id, search.redirect)
    } catch {
      setProviderError(true)
    }
  }

  const retrySession = async () => {
    setIsRetrying(true)
    try {
      await auth.refreshSession()
    } finally {
      setIsRetrying(false)
    }
  }

  const signInWithPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isSigningIn) {
      return
    }
    setIsSigningIn(true)
    setPasswordError(false)
    setProviderError(false)
    try {
      await auth.passwordLogin(username, password)
    } catch {
      setPasswordError(true)
    } finally {
      setPassword('')
      setIsSigningIn(false)
    }
  }

  const providerLabel = (id: string) => {
    if (id === 'google' || id === 'dingtalk' || id === 'phone') {
      return t(`providers.${id}`)
    }
    return id
  }

  return (
    <main className="relative flex min-h-dvh items-center justify-center bg-background px-4 py-24 text-foreground">
      <div className="absolute right-4 top-4 flex items-center gap-2 md:right-8 md:top-6">
        <LanguageSwitcher compact />
        <ThemeConfigurator />
      </div>
      <section className="w-full max-w-md rounded-lg border border-border bg-card p-6 text-card-foreground md:p-8">
        <div className="mb-6 inline-flex size-12 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <ShieldCheck className="size-6" aria-hidden="true" />
        </div>
        <p className="mb-2 text-sm font-medium text-muted-foreground">{t('appName', { ns: 'common' })}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t('title')}</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">{t('description')}</p>

        {search.error || providerError || passwordError || auth.error ? (
          <p
            role="alert"
            className="mt-6 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {auth.error
              ? t('errors.sessionUnavailable')
              : passwordError
                ? t('errors.passwordFailed')
                : providerError
                  ? t('errors.providerUnavailable')
                  : t(search.error?.endsWith('_denied') ? 'errors.oauthDenied' : 'errors.oauthFailed')}
          </p>
        ) : null}

        {auth.status === 'loading' || auth.status === 'authenticated' ? (
          <p role="status" className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            {t('loading')}
          </p>
        ) : auth.status === 'error' ? (
          <button
            type="button"
            onClick={() => void retrySession()}
            disabled={isRetrying}
            className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-3 font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-50"
          >
            {isRetrying ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
            {t('retry')}
          </button>
        ) : (
          <div className="mt-6 space-y-3">
            {passwordProvider ? (
              <form onSubmit={(event) => void signInWithPassword(event)}>
                <fieldset disabled={isSigningIn || !passwordProvider.implemented} className="space-y-4">
                  <legend className="sr-only">{t('password.signIn')}</legend>
                  <div className="space-y-2">
                    <label htmlFor="login-username" className="block text-sm font-medium">
                      {t('password.username')}
                    </label>
                    <input
                      id="login-username"
                      name="username"
                      type="text"
                      autoComplete="username"
                      autoCapitalize="none"
                      spellCheck={false}
                      required
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      className="min-h-12 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    />
                  </div>
                  <div className="space-y-2">
                    <label htmlFor="login-password" className="block text-sm font-medium">
                      {t('password.password')}
                    </label>
                    <input
                      id="login-password"
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className="min-h-12 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    />
                  </div>
                  <button
                    type="submit"
                    className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-3 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-50"
                  >
                    {isSigningIn ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
                    {t(isSigningIn ? 'password.signingIn' : 'password.signIn')}
                  </button>
                </fieldset>
              </form>
            ) : null}
            {availableProviders.map((provider) => {
              if (provider.id === 'password' && provider.method === 'password') {
                return null
              }
              const isAvailable = provider.implemented && provider.method === 'oauth' && Boolean(provider.start_path)
              const Icon = provider.id === 'phone' ? Smartphone : provider.id === 'dingtalk' ? Building2 : Globe
              return (
                <button
                  key={provider.id}
                  type="button"
                  disabled={!isAvailable || isSigningIn}
                  onClick={() => startOAuth(provider)}
                  className="flex min-h-12 w-full items-center gap-3 rounded-md border border-border bg-background px-4 py-3 text-sm font-medium transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Icon className="size-5 shrink-0" aria-hidden="true" />
                  <span>{t('continueWith', { provider: providerLabel(provider.id) })}</span>
                  {isAvailable ? (
                    <ArrowRight className="ml-auto size-4 shrink-0" aria-hidden="true" />
                  ) : (
                    <span className="ml-auto text-xs">{t('comingSoon')}</span>
                  )}
                </button>
              )
            })}
            {!hasLoginProvider ? <p className="text-sm leading-6 text-muted-foreground">{t('noProviders')}</p> : null}
          </div>
        )}
        <p className="mt-6 text-xs leading-5 text-muted-foreground">{t('returnHint')}</p>
      </section>
    </main>
  )
}
