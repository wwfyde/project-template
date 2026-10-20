import { ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { AccountRead } from '../model/account'
import { buttonClass, cardClass, inputClass, primaryButtonClass } from './styles'

export function ReauthenticationPanel({
  account,
  busy,
  onPassword,
  onOAuth,
}: {
  account: AccountRead
  busy: boolean
  onPassword: (password: string) => Promise<boolean>
  onOAuth: (provider: string) => void
}) {
  const { t } = useTranslation('account')
  const [password, setPassword] = useState('')
  const available = account.providers.filter(
    (provider) =>
      provider.enabled &&
      provider.implemented &&
      account.identities.some((identity) => identity.provider === provider.id && identity.enabled),
  )
  const hasPassword = available.some((provider) => provider.id === 'password')
  const oauthProviders = available.filter(
    (provider) => provider.method === 'oauth' && (provider.id === 'google' || provider.id === 'dingtalk'),
  )

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    try {
      await onPassword(password)
    } finally {
      setPassword('')
    }
  }

  return (
    <section className={`${cardClass} border-primary/40`} aria-labelledby="verification-heading">
      <div className="flex items-center gap-3">
        <ShieldCheck className="size-5 text-primary" aria-hidden="true" />
        <h2 id="verification-heading" className="text-lg font-semibold">
          {t('verification.title')}
        </h2>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{t('verification.description')}</p>
      {hasPassword ? (
        <form onSubmit={(event) => void submit(event)} className="mt-5 flex flex-wrap items-end gap-3">
          <label className="min-w-48 flex-1 text-sm font-medium">
            {t('verification.password')}
            <input
              className={inputClass}
              type="password"
              autoComplete="current-password"
              name="verification_password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={1024}
              disabled={busy}
            />
          </label>
          <button className={primaryButtonClass} disabled={busy}>
            {t('verification.submit')}
          </button>
        </form>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        {oauthProviders.map((provider) => (
          <button
            key={provider.id}
            type="button"
            className={buttonClass}
            disabled={busy}
            onClick={() => onOAuth(provider.id)}
          >
            {t('verification.provider', { provider: t(`methods.providers.${provider.id as 'google' | 'dingtalk'}`) })}
          </button>
        ))}
      </div>
      {!hasPassword && !oauthProviders.length ? (
        <p className="mt-4 text-sm text-muted-foreground">{t('verification.noMethod')}</p>
      ) : null}
    </section>
  )
}
