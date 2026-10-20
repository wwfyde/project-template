import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { AccountIdentity, PasswordUpdate } from '../model/account'
import { inputClass, primaryButtonClass } from './styles'

export function PasswordForm({
  identity,
  disabled,
  onSave,
}: {
  identity?: AccountIdentity
  disabled: boolean
  onSave: (password: PasswordUpdate) => Promise<boolean>
}) {
  const { t } = useTranslation('account')
  const [username, setUsername] = useState(identity?.username ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [mismatch, setMismatch] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setMismatch(password !== confirmation)
    if (password !== confirmation) return
    try {
      const saved = await onSave({
        ...(identity ? { current_password: currentPassword } : { username: username.trim() }),
        password,
      })
      if (saved) {
        setPassword('')
        setConfirmation('')
      }
    } finally {
      setCurrentPassword('')
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-5 space-y-4">
      <fieldset disabled={disabled} className="space-y-4">
        <label className="block text-sm font-medium">
          {t('password.username')}
          <input
            className={inputClass}
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            readOnly={Boolean(identity)}
            required
            minLength={3}
            maxLength={64}
            pattern="[A-Za-z0-9_.@\-]{3,64}"
            aria-describedby="username-hint"
          />
          {!identity ? (
            <span id="username-hint" className="mt-2 block text-xs font-normal leading-5 text-muted-foreground">
              {t('password.usernameHint')}
            </span>
          ) : null}
        </label>
        {identity ? (
          <label className="block text-sm font-medium">
            {t('password.current')}
            <input
              className={inputClass}
              name="current_password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              maxLength={1024}
            />
          </label>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-medium">
            {t('password.new')}
            <input
              className={inputClass}
              name="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={12}
              maxLength={1024}
              aria-describedby="password-hint"
            />
          </label>
          <label className="block text-sm font-medium">
            {t('password.confirm')}
            <input
              className={inputClass}
              name="confirm_password"
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              minLength={12}
              maxLength={1024}
              aria-invalid={mismatch}
              aria-describedby={mismatch ? 'password-mismatch' : undefined}
            />
          </label>
        </div>
        <p id="password-hint" className="text-xs leading-5 text-muted-foreground">
          {t('password.hint')}
        </p>
        {mismatch ? (
          <p id="password-mismatch" role="alert" className="text-sm text-destructive">
            {t('errors.password_mismatch')}
          </p>
        ) : null}
        <button className={primaryButtonClass}>{t(identity ? 'password.update' : 'password.set')}</button>
      </fieldset>
    </form>
  )
}
