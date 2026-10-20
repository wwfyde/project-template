import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { AuthUser } from '../../auth'
import type { ProfileUpdate } from '../model/account'
import { cardClass, inputClass, primaryButtonClass } from './styles'

export function ProfileForm({
  user,
  busy,
  onSave,
}: {
  user: AuthUser
  busy: boolean
  onSave: (profile: ProfileUpdate) => Promise<boolean>
}) {
  const { t } = useTranslation('account')
  const [displayName, setDisplayName] = useState(user.display_name)
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url ?? '')
  const dirty = displayName !== user.display_name || avatarUrl !== (user.avatar_url ?? '')

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await onSave({ display_name: displayName.trim(), avatar_url: avatarUrl.trim() || null })
  }

  return (
    <section className={cardClass} aria-labelledby="profile-heading">
      <h2 id="profile-heading" className="text-lg font-semibold">
        {t('profile.title')}
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{t('profile.description')}</p>
      <form onSubmit={(event) => void submit(event)} className="mt-6 space-y-5">
        <label className="block text-sm font-medium">
          {t('profile.displayName')}
          <input
            className={inputClass}
            name="display_name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            required
            maxLength={255}
            autoComplete="nickname"
            disabled={busy}
          />
        </label>
        <label className="block text-sm font-medium">
          {t('profile.avatarUrl')}
          <input
            className={inputClass}
            name="avatar_url"
            type="url"
            pattern="https://.*"
            maxLength={2048}
            value={avatarUrl}
            onChange={(event) => setAvatarUrl(event.target.value)}
            aria-describedby="avatar-hint"
            disabled={busy}
          />
          <span id="avatar-hint" className="mt-2 block text-xs font-normal leading-5 text-muted-foreground">
            {t('profile.avatarHint')}
          </span>
        </label>
        <dl className="grid gap-4 rounded-md bg-muted/50 p-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t('profile.email')}</dt>
            <dd className="mt-1 break-all">{user.email ?? t('notProvided')}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('profile.phone')}</dt>
            <dd className="mt-1 break-all">{user.phone ?? t('notProvided')}</dd>
          </div>
        </dl>
        <p className="text-xs leading-5 text-muted-foreground">{t('profile.contactHint')}</p>
        <button className={primaryButtonClass} disabled={busy || !dirty || !displayName.trim()}>
          {t('save')}
        </button>
      </form>
    </section>
  )
}
