import { useNavigate, useSearch } from '@tanstack/react-router'
import { Building2, Globe, KeyRound, LoaderCircle } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiRequestError } from '../../../lib/api-client'
import { useAuth } from '../../auth'
import { createAccountClient } from '../infrastructure/account-client'
import { accountErrorCode, type AccountErrorCode, type AccountIdentity, type AccountRead } from '../model/account'
import { PasswordForm } from './password-form'
import { ProfileForm } from './profile-form'
import { ReauthenticationPanel } from './reauthentication-panel'
import { buttonClass, cardClass } from './styles'

const methods = [
  { id: 'google', icon: Globe },
  { id: 'dingtalk', icon: Building2 },
  { id: 'password', icon: KeyRound },
] as const
type SuccessMessage = 'profile' | 'linked' | 'unlinked' | 'password' | 'reauthenticated'
type ErrorMessage = { code: AccountErrorCode; requestId?: string }

export function AccountPage() {
  const auth = useAuth()
  const { authenticatedRequest } = auth
  const client = useMemo(() => createAccountClient({ authenticatedRequest }), [authenticatedRequest])
  const navigate = useNavigate()
  const search = useSearch({ from: '/_authenticated/account' })
  const { t } = useTranslation('account')
  const [account, setAccount] = useState<AccountRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ErrorMessage | null>(search.account_error ? { code: search.account_error } : null)
  const [success, setSuccess] = useState<SuccessMessage | null>(search.account_action ?? null)
  const [verificationRequired, setVerificationRequired] = useState(false)
  const [unlinkTarget, setUnlinkTarget] = useState<AccountIdentity | null>(null)

  const reportError = useCallback((reason: unknown) => {
    const code = reason instanceof ApiRequestError ? accountErrorCode(reason.code) : 'request_failed'
    setError({ code, requestId: reason instanceof ApiRequestError ? reason.requestId : undefined })
    if (code === 'reauthentication_required') setVerificationRequired(true)
    setSuccess(null)
  }, [])

  const load = useCallback(async () => {
    const data = await client.read()
    setAccount(data)
    setVerificationRequired(data.reauthentication.required)
  }, [client])

  useEffect(() => {
    let active = true
    void client
      .read()
      .then((data) => {
        if (active) {
          setAccount(data)
          setVerificationRequired(data.reauthentication.required)
        }
      })
      .catch((reason: unknown) => {
        if (active) reportError(reason)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [client, reportError])

  useEffect(() => {
    if (!account || account.reauthentication.required) return
    const timeout = window.setTimeout(() => setVerificationRequired(true), account.reauthentication.expires_in * 1000)
    return () => window.clearTimeout(timeout)
  }, [account])

  // Query parameters are an allow-listed message only. The account and session
  // are always fetched from the server after the OAuth callback.
  useEffect(() => {
    if (search.account_action || search.account_error) {
      void navigate({ to: '/account', search: {}, replace: true })
    }
  }, [navigate, search.account_action, search.account_error])

  const run = async (action: () => Promise<unknown>, message?: SuccessMessage): Promise<boolean> => {
    if (busy) return false
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      await action()
      await load()
      setSuccess(message ?? null)
      return true
    } catch (reason) {
      reportError(reason)
      return false
    } finally {
      setBusy(false)
    }
  }

  const startOAuth = (provider: string, reauthenticate = false) => {
    void run(() => client.startOAuth(provider, reauthenticate))
  }

  const unlink = async () => {
    if (!unlinkTarget || busy) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await client.unlink(unlinkTarget.id)
      setUnlinkTarget(null)
      if (result.requires_login) {
        await navigate({ to: '/login', search: { redirect: '/account' }, replace: true })
        return
      }
      await load()
      setSuccess('unlinked')
    } catch (reason) {
      reportError(reason)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">{t('title')}</h1>
        <p className="mt-3 text-muted-foreground">{t('description')}</p>
      </header>
      {error ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
        >
          <p>{t(`errors.${error.code}`)}</p>
          {error.requestId ? (
            <p className="mt-2 break-all font-mono text-xs">{t('requestId', { id: error.requestId })}</p>
          ) : null}
        </div>
      ) : null}
      {success ? (
        <p role="status" className="rounded-md border border-primary/25 bg-primary/5 p-4 text-sm">
          {t(`success.${success}`)}
        </p>
      ) : null}
      {loading ? (
        <p role="status" className="flex items-center gap-2 text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          {t('loading')}
        </p>
      ) : !account ? (
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run(load)}>
          {t('retry')}
        </button>
      ) : (
        <>
          {verificationRequired ? (
            <ReauthenticationPanel
              account={account}
              busy={busy}
              onPassword={(password) => run(() => client.reauthenticatePassword(password), 'reauthenticated')}
              onOAuth={(provider) => startOAuth(provider, true)}
            />
          ) : null}
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <ProfileForm
              key={`${account.user.display_name}:${account.user.avatar_url ?? ''}`}
              user={account.user}
              busy={busy}
              onSave={(profile) => run(() => client.updateProfile(profile), 'profile')}
            />
            <section className={cardClass} aria-labelledby="methods-heading">
              <h2 id="methods-heading" className="text-lg font-semibold">
                {t('methods.title')}
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{t('methods.description')}</p>
              {verificationRequired ? <p className="mt-3 text-sm text-primary">{t('verification.required')}</p> : null}
              <div className="mt-3 divide-y divide-border">
                {methods.map(({ id, icon: Icon }) => {
                  const identity = account.identities.find((candidate) => candidate.provider === id)
                  const provider = account.providers.find((candidate) => candidate.id === id)
                  const enabled = Boolean(provider?.enabled && provider.implemented)
                  const label = t(`methods.providers.${id}`)
                  return (
                    <div key={id} className="py-5">
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/50">
                          <Icon className="size-5" aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="text-sm font-semibold">{label}</h3>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t(identity ? 'methods.linked' : 'methods.unlinked')}
                            {identity?.current ? ` · ${t('methods.current')}` : ''}
                          </p>
                        </div>
                        {identity ? (
                          <button
                            type="button"
                            className={buttonClass}
                            disabled={busy || verificationRequired || !identity.can_unlink}
                            onClick={() => setUnlinkTarget(identity)}
                          >
                            {t('methods.unlink')}
                          </button>
                        ) : id !== 'password' ? (
                          <button
                            type="button"
                            className={buttonClass}
                            disabled={busy || verificationRequired || !enabled}
                            onClick={() => startOAuth(id)}
                          >
                            {t('methods.link', { provider: label })}
                          </button>
                        ) : null}
                      </div>
                      {!enabled ? (
                        <p className="mt-3 text-xs text-muted-foreground">{t('methods.unavailable')}</p>
                      ) : null}
                      {identity && !identity.can_unlink ? (
                        <p className="mt-3 text-xs text-muted-foreground">{t('methods.lastMethod')}</p>
                      ) : null}
                      {unlinkTarget?.id === identity?.id && identity ? (
                        <div
                          role="group"
                          aria-label={t('methods.confirmTitle', { provider: label })}
                          className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 p-4"
                        >
                          <p className="text-sm font-semibold">{t('methods.confirmTitle', { provider: label })}</p>
                          <p className="mt-2 text-sm leading-6 text-muted-foreground">
                            {t('methods.confirmDescription')}
                          </p>
                          {identity.current ? (
                            <p className="mt-2 text-sm text-destructive">{t('methods.currentWarning')}</p>
                          ) : null}
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              type="button"
                              className={`${buttonClass} text-destructive`}
                              disabled={busy || verificationRequired}
                              onClick={() => void unlink()}
                            >
                              {t('methods.confirmUnlink')}
                            </button>
                            <button
                              type="button"
                              className={buttonClass}
                              disabled={busy}
                              onClick={() => setUnlinkTarget(null)}
                            >
                              {t('cancel')}
                            </button>
                          </div>
                        </div>
                      ) : null}
                      {id === 'password' && enabled ? (
                        <PasswordForm
                          key={identity?.id ?? 'new-password'}
                          identity={identity}
                          disabled={busy || verificationRequired}
                          onSave={(password) => run(() => client.setPassword(password), 'password')}
                        />
                      ) : null}
                    </div>
                  )
                })}
              </div>
              <p className="border-t border-border pt-4 text-xs leading-5 text-muted-foreground">
                {t('methods.conflictHint')}
              </p>
            </section>
          </div>
        </>
      )}
    </div>
  )
}
