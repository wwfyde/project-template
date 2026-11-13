import { BookOpen, Download, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiRequestError } from '../../../lib/api-client'
import { useAuth } from '../../auth'
import { createSkillClient, skillContentPath, type SkillClient } from '../infrastructure/skill-client'
import {
  mergeSkillPage,
  validateSkillUpload,
  type Skill,
  type SkillList,
  type SkillUpload,
  type SkillVersion,
} from '../model/skill'
import { SkillPreview } from './skill-preview'
import { SkillUploadButtons } from './skill-upload'
import './skills.css'

type Mutation = (operation: () => Promise<void>) => Promise<void>

export function SkillsPage() {
  const { user, authenticatedRequest } = useAuth()
  const client = useMemo(() => createSkillClient({ authenticatedRequest }), [authenticatedRequest])
  // Never retain another account's list, file contents or in-flight UI updates.
  return <SkillsWorkspace key={`${user?.account_id}:${user?.id}`} client={client} />
}

function SkillsWorkspace({ client }: { client: SkillClient }) {
  const { t } = useTranslation('skills')
  const [skills, setSkills] = useState<Skill[]>([])
  const [page, setPage] = useState<SkillList<Skill> | null>(null)
  const [selected, setSelected] = useState<Skill | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const mutationLock = useRef(false)
  const listRevision = useRef(0)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const revision = ++listRevision.current
    setLoading(true)
    setListError(null)
    void client
      .list({ signal: controller.signal })
      .then((result) => {
        if (!alive.current || listRevision.current !== revision) return
        setSkills(result.data)
        setPage(result)
        setSelected((current) => (current ? (result.data.find((item) => item.id === current.id) ?? current) : null))
      })
      .catch((cause: unknown) => {
        if (alive.current && listRevision.current === revision && !controller.signal.aborted) {
          setListError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
        }
      })
      .finally(() => {
        if (alive.current && listRevision.current === revision) setLoading(false)
      })
    return () => {
      controller.abort()
      listRevision.current += 1
    }
  }, [client, reload, t])

  const loadMore = async () => {
    if (loading || !page?.has_more || !page.last_id) return
    const revision = ++listRevision.current
    setLoading(true)
    setListError(null)
    try {
      const result = await client.list({ after: page.last_id })
      if (alive.current && revision === listRevision.current) {
        setSkills((current) => mergeSkillPage(current, result.data))
        setPage(result)
      }
    } catch (cause) {
      if (alive.current && revision === listRevision.current) {
        setListError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
      }
    } finally {
      if (alive.current && revision === listRevision.current) setLoading(false)
    }
  }

  const mutate: Mutation = async (operation) => {
    if (mutationLock.current) return
    mutationLock.current = true
    setBusy(true)
    setError(null)
    try {
      await operation()
    } catch (cause) {
      if (alive.current) setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
    } finally {
      mutationLock.current = false
      if (alive.current) setBusy(false)
    }
  }

  const updateSkill = (skill: Skill) => {
    if (!alive.current) return
    setSkills((current) => current.map((item) => (item.id === skill.id ? skill : item)))
    setSelected((current) => (current?.id === skill.id ? skill : current))
  }

  const removeSkill = (id: string) => {
    if (!alive.current) return
    setSkills((current) => current.filter((item) => item.id !== id))
    setSelected((current) => (current?.id === id ? null : current))
    setReload((value) => value + 1)
  }

  const create = (upload: SkillUpload) => {
    const validation = validateSkillUpload(upload)
    if (validation) {
      setError(t(`errors.${validation}`))
      return
    }
    void mutate(async () => {
      const skill = await client.create(upload)
      if (!alive.current) return
      setSkills((current) => [skill, ...current.filter((item) => item.id !== skill.id)])
      setSelected(skill)
    })
  }

  return (
    <section className="space-y-5" aria-busy={busy}>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{t('title')}</h1>
          <p className="text-muted-foreground">{t('description')}</p>
        </div>
        <fieldset className="space-y-2" disabled={busy}>
          <legend className="mb-2 text-sm font-medium">{t('create')}</legend>
          <SkillUploadButtons disabled={busy || loading} onUpload={create} />
        </fieldset>
      </header>
      <p className="text-sm text-muted-foreground">{t('uploadHint')}</p>
      {error && (
        <p role="alert" className="skill-error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="text-sm text-muted-foreground">
          {t('saving')}
        </p>
      )}
      <div className="grid items-start gap-5 xl:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="skill-panel overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-border p-3">
            <h2 className="text-sm font-semibold">{t('skillsList')}</h2>
            <button
              type="button"
              className="skill-button"
              disabled={loading || busy}
              title={t('refresh')}
              aria-label={t('refresh')}
              onClick={() => setReload((value) => value + 1)}
            >
              <RefreshCw size={15} aria-hidden="true" />
            </button>
          </div>
          {listError && (
            <div className="skill-error m-3 space-y-2" role="alert">
              <p>{listError}</p>
              <button
                type="button"
                className="skill-button"
                disabled={busy || loading}
                onClick={() => setReload((value) => value + 1)}
              >
                {t('retry')}
              </button>
            </div>
          )}
          {skills.length > 0 ? (
            <ul className="max-h-[32rem] overflow-auto p-2">
              {skills.map((skill) => (
                <li key={skill.id}>
                  <button
                    type="button"
                    className="skill-list-item"
                    disabled={busy}
                    aria-current={selected?.id === skill.id ? 'true' : undefined}
                    onClick={() => {
                      setSelected(skill)
                      setError(null)
                    }}
                  >
                    <span className="block truncate font-medium">{skill.name}</span>
                    <span className="mt-1 line-clamp-2 block text-xs text-muted-foreground">{skill.description}</span>
                    <span className="mt-2 block text-xs text-muted-foreground">
                      v{skill.default_version} · {t('defaultVersion')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : !loading && !listError ? (
            <p className="p-5 text-sm text-muted-foreground">{t('empty')}</p>
          ) : null}
          {loading && (
            <p role="status" className="p-3 text-sm text-muted-foreground">
              {t('loading')}
            </p>
          )}
          {page?.has_more && (
            <div className="border-t border-border p-3">
              <button
                type="button"
                className="skill-button w-full"
                disabled={loading || busy}
                onClick={() => void loadMore()}
              >
                {t('loadMore')}
              </button>
            </div>
          )}
        </aside>
        {selected ? (
          <SkillDetails
            key={selected.id}
            skill={selected}
            client={client}
            busy={busy || loading}
            mutate={mutate}
            onChange={updateSkill}
            onRemove={removeSkill}
            onError={setError}
          />
        ) : (
          <div className="skill-panel flex min-h-80 flex-col items-center justify-center gap-4 border-dashed p-8 text-center text-muted-foreground">
            <BookOpen size={36} strokeWidth={1.3} aria-hidden="true" />
            <p>{t('selectSkill')}</p>
          </div>
        )}
      </div>
    </section>
  )
}

type SkillDetailsProps = {
  skill: Skill
  client: SkillClient
  busy: boolean
  mutate: Mutation
  onChange: (skill: Skill) => void
  onRemove: (id: string) => void
  onError: (message: string) => void
}

function SkillDetails({ skill, client, busy, mutate, onChange, onRemove, onError }: SkillDetailsProps) {
  const { t } = useTranslation('skills')
  const [versions, setVersions] = useState<SkillVersion[]>([])
  const [page, setPage] = useState<SkillList<SkillVersion> | null>(null)
  const [version, setVersion] = useState(skill.default_version)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [confirmation, setConfirmation] = useState<'skill' | 'version' | null>(null)
  const alive = useRef(true)
  const revision = useRef(0)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const currentRevision = ++revision.current
    setLoading(true)
    setError(null)
    void client
      .versions(skill.id, { signal: controller.signal })
      .then((result) => {
        if (alive.current && revision.current === currentRevision) {
          setVersions(result.data)
          setPage(result)
        }
      })
      .catch((cause: unknown) => {
        if (alive.current && revision.current === currentRevision && !controller.signal.aborted) {
          setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
        }
      })
      .finally(() => {
        if (alive.current && revision.current === currentRevision) setLoading(false)
      })
    return () => {
      controller.abort()
      revision.current += 1
    }
  }, [client, skill.id, reload, t])

  const moreVersions = async () => {
    if (loading || !page?.has_more || !page.last_id) return
    const currentRevision = ++revision.current
    setLoading(true)
    setError(null)
    try {
      const result = await client.versions(skill.id, { after: page.last_id })
      if (alive.current && revision.current === currentRevision) {
        setVersions((current) => mergeSkillPage(current, result.data))
        setPage(result)
      }
    } catch (cause) {
      if (alive.current && revision.current === currentRevision)
        setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
    } finally {
      if (alive.current && revision.current === currentRevision) setLoading(false)
    }
  }

  const uploadVersion = (upload: SkillUpload) => {
    const validation = validateSkillUpload(upload)
    if (validation) {
      onError(t(`errors.${validation}`))
      return
    }
    void mutate(async () => {
      const created = await client.createVersion(skill.id, upload)
      if (!alive.current) return
      setVersion(created.version)
      setReload((value) => value + 1)
      onChange(await client.get(skill.id))
    })
  }

  const setDefault = () =>
    void mutate(async () => {
      const updated = await client.setDefault(skill.id, version)
      if (alive.current) {
        setConfirmation(null)
        onChange(updated)
      }
    })

  const remove = () =>
    void mutate(async () => {
      if (confirmation === 'skill') {
        await client.delete(skill.id)
        if (alive.current) onRemove(skill.id)
        return
      }
      await client.deleteVersion(skill.id, version)
      if (!alive.current) return
      setConfirmation(null)
      try {
        const updated = await client.get(skill.id)
        if (!alive.current) return
        onChange(updated)
        setVersion(updated.default_version)
        setReload((value) => value + 1)
      } catch (cause) {
        if (cause instanceof ApiRequestError && cause.status === 404) {
          onRemove(skill.id)
          return
        }
        throw cause
      }
    })

  const lastVersion = !!page && !page.has_more && versions.length === 1
  const defaultProtected = version === skill.default_version && !lastVersion
  const versionOptions = versions.some((item) => item.version === version)
    ? versions.map((item) => item.version)
    : [version, ...versions.map((item) => item.version)]

  return (
    <article className="skill-panel min-w-0 overflow-hidden">
      <header className="space-y-4 border-b border-border p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="break-words text-lg font-semibold">{skill.name}</h2>
            <p className="max-w-3xl break-words text-sm text-muted-foreground">{skill.description}</p>
          </div>
          <button
            type="button"
            className="skill-button text-destructive"
            disabled={busy}
            onClick={() => setConfirmation('skill')}
          >
            <Trash2 size={15} aria-hidden="true" />
            {t('deleteSkill')}
          </button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="grid gap-1 text-xs text-muted-foreground">
            {t('version')}
            <select
              className="skill-field min-w-36"
              value={version}
              disabled={busy || loading}
              onChange={(event) => {
                setVersion(event.target.value)
                setConfirmation(null)
              }}
            >
              {versionOptions.map((value) => (
                <option key={value} value={value}>
                  v{value}
                  {value === skill.default_version ? ` · ${t('defaultVersion')}` : ''}
                  {value === skill.latest_version ? ` · ${t('latestVersion')}` : ''}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="skill-button"
            disabled={busy || version === skill.default_version}
            onClick={setDefault}
          >
            {t('setDefault')}
          </button>
          <a className="skill-button" href={skillContentPath(skill.id, version)} download>
            {/* Cookie auth; bytes never go through the JSON client. */}
            <Download size={15} aria-hidden="true" />
            {t('download')}
          </a>
          <button
            type="button"
            className="skill-button text-destructive"
            disabled={busy || loading || !!error || defaultProtected}
            title={defaultProtected ? t('defaultDeleteHint') : undefined}
            onClick={() => setConfirmation('version')}
          >
            {t('deleteVersion')}
          </button>
          {page?.has_more && (
            <button
              type="button"
              className="skill-button"
              disabled={busy || loading}
              onClick={() => void moreVersions()}
            >
              {t('loadMoreVersions')}
            </button>
          )}
        </div>
        {loading && (
          <p role="status" className="text-xs text-muted-foreground">
            {t('loading')}
          </p>
        )}
        {defaultProtected && <p className="text-xs text-muted-foreground">{t('defaultDeleteHint')}</p>}
        {error && (
          <div className="skill-error flex flex-wrap items-center gap-3" role="alert">
            <p>{error}</p>
            <button
              type="button"
              className="skill-button"
              disabled={busy || loading}
              onClick={() => setReload((value) => value + 1)}
            >
              {t('retry')}
            </button>
          </div>
        )}
        {confirmation && (
          <div className="skill-error space-y-3" role="alert">
            <p>
              {confirmation === 'skill'
                ? t('confirmDeleteSkill', { name: skill.name })
                : t('confirmDeleteVersion', { name: skill.name, version })}
            </p>
            {confirmation === 'version' && lastVersion && <p>{t('deleteLastVersion')}</p>}
            <div className="flex flex-wrap gap-2">
              <button type="button" className="skill-button" disabled={busy} onClick={remove}>
                {t('confirmDelete')}
              </button>
              <button type="button" className="skill-button" disabled={busy} onClick={() => setConfirmation(null)}>
                {t('cancel')}
              </button>
            </div>
          </div>
        )}
      </header>
      <SkillPreview client={client} skillId={skill.id} version={version} />
      <fieldset disabled={busy} className="space-y-2 border-t border-border p-4">
        <legend className="sr-only">{t('newVersion')}</legend>
        <h3 className="text-sm font-medium">{t('newVersion')}</h3>
        <p className="text-xs text-muted-foreground">{t('newVersionHint')}</p>
        <SkillUploadButtons disabled={busy || loading} onUpload={uploadVersion} />
      </fieldset>
    </article>
  )
}
