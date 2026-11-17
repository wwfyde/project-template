import { Check, CircleDashed, LoaderCircle, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState, type RefObject } from 'react'

import { Dialog } from '../../../components/ui/dialog'
import type { Skill, SkillClient } from '../../skills'
import type { AgentActionsCopy } from '../model/action-translations'
import {
  MAX_CONTEXT_TEXT_LENGTH,
  MAX_CONTEXT_TITLE_LENGTH,
  MAX_CONTEXT_URL_LENGTH,
  contextKey,
  normalizeContextUrl,
  type ContextReference,
} from '../model/context'

export type ContextDialogKind = 'link' | 'text' | 'skill'

type AgentContextDialogProps = {
  kind: ContextDialogKind
  copy: AgentActionsCopy
  existing: ContextReference[]
  skillClient: Pick<SkillClient, 'list'>
  onAdd: (reference: ContextReference) => string | null
  onClose: () => void
  returnFocusRef: RefObject<HTMLTextAreaElement | null>
}

const inputClass =
  'w-full rounded-xl border border-agent-border bg-agent-canvas px-3 py-2.5 text-base text-agent-text outline-none placeholder:text-agent-muted focus:border-agent-muted focus:ring-1 focus:ring-agent-muted sm:text-sm'
const primaryClass =
  'inline-flex min-h-10 items-center justify-center rounded-full bg-agent-strong px-5 text-sm font-medium text-agent-on-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-agent-muted disabled:opacity-40'
const secondaryClass =
  'inline-flex min-h-10 items-center justify-center rounded-full px-4 text-sm text-agent-muted hover:bg-agent-subtle focus-visible:outline-2 focus-visible:outline-agent-muted'

function SkillContextPicker({
  copy,
  client,
  existing,
  onAdd,
  onClose,
  inputRef,
}: {
  copy: AgentActionsCopy
  client: Pick<SkillClient, 'list'>
  existing: ContextReference[]
  onAdd: AgentContextDialogProps['onAdd']
  onClose: () => void
  inputRef: RefObject<HTMLInputElement | null>
}) {
  const [query, setQuery] = useState('')
  const [request, setRequest] = useState<{ after?: string; attempt: number }>({ attempt: 0 })
  const [catalog, setCatalog] = useState<{ items: Skill[]; phase: 'loading' | 'ready' | 'error'; next?: string }>({
    items: [],
    phase: 'loading',
  })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void client
      .list({ after: request.after, limit: 30, signal: controller.signal })
      .then((page) => {
        if (controller.signal.aborted) return
        if (!Array.isArray(page.data)) throw new Error('Invalid skill list')
        setCatalog((current) => ({
          items: [
            ...new Map(
              [...(request.after ? current.items : []), ...page.data].map((skill) => [skill.id, skill]),
            ).values(),
          ],
          phase: 'ready',
          next: page.has_more && page.last_id && page.last_id !== request.after ? page.last_id : undefined,
        }))
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalog((current) => ({ ...current, phase: 'error' }))
      })
    return () => controller.abort()
  }, [client, request])

  const selected = new Set(existing.map(contextKey))
  const matches = catalog.items.filter((skill) =>
    `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  )
  const load = (after?: string) => {
    setCatalog((current) => ({ ...current, phase: 'loading' }))
    setRequest((current) => ({ after, attempt: current.attempt + 1 }))
  }

  return (
    <div className="space-y-4">
      <label className="relative block">
        <span className="sr-only">{copy.searchSkills}</span>
        <Search size={16} className="pointer-events-none absolute left-3 top-3.5 text-agent-muted" aria-hidden="true" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={copy.searchSkills}
          className={`${inputClass} pl-10`}
        />
      </label>
      {catalog.phase === 'loading' ? (
        <p role="status" className="flex items-center gap-2 text-sm text-agent-muted">
          <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
          {copy.skillLoading}
        </p>
      ) : null}
      {catalog.phase === 'error' ? (
        <div className="rounded-xl border border-agent-border bg-agent-subtle p-4">
          <p role="alert" className="text-sm leading-6">
            {copy.skillError}
          </p>
          <button
            type="button"
            className={`${secondaryClass} mt-2 border border-agent-border`}
            onClick={() => load(request.after)}
          >
            {copy.skillRetry}
          </button>
        </div>
      ) : null}
      {catalog.phase === 'ready' && matches.length === 0 ? (
        <p role="status" className="py-8 text-center text-sm text-agent-muted">
          {catalog.items.length ? copy.skillNoMatch : copy.skillEmpty}
        </p>
      ) : null}
      <div className="max-h-[min(340px,42dvh)] space-y-1 overflow-y-auto">
        {matches.map((skill) => {
          const reference: ContextReference = {
            id: crypto.randomUUID(),
            kind: 'skill',
            title: skill.name.slice(0, MAX_CONTEXT_TITLE_LENGTH),
            skillId: skill.id,
            version: skill.default_version,
            description: skill.description.slice(0, MAX_CONTEXT_TEXT_LENGTH),
          }
          const added = selected.has(contextKey(reference))
          return (
            <button
              key={skill.id}
              type="button"
              disabled={added || !skill.default_version}
              onClick={() => {
                const result = onAdd(reference)
                setError(result)
                if (!result) onClose()
              }}
              className="flex w-full items-start gap-3 rounded-xl p-3 text-left hover:bg-agent-subtle focus-visible:outline-2 focus-visible:outline-agent-muted disabled:cursor-default disabled:opacity-50"
            >
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-agent-border">
                <CircleDashed size={17} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{skill.name}</span>
                <span className="mt-1 block line-clamp-2 text-xs leading-5 text-agent-muted">{skill.description}</span>
                <span className="mt-1 block text-[11px] text-agent-muted">
                  {skill.default_version ? `v${skill.default_version}` : copy.skillUnavailable}
                </span>
              </span>
              {added ? (
                <span className="flex shrink-0 items-center gap-1 text-xs text-agent-muted">
                  <Check size={13} aria-hidden="true" />
                  {copy.skillSelected}
                </span>
              ) : null}
            </button>
          )
        })}
      </div>
      {catalog.next && catalog.phase === 'ready' ? (
        <button
          type="button"
          className={`${secondaryClass} w-full border border-agent-border`}
          onClick={() => load(catalog.next)}
        >
          {copy.skillMore}
        </button>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function AgentContextDialog({
  kind,
  copy,
  existing,
  skillClient,
  onAdd,
  onClose,
  returnFocusRef,
}: AgentContextDialogProps) {
  const id = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState('')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const headings = { link: copy.addLink, text: copy.addText, skill: copy.addSkill }
  const descriptions = { link: copy.linkHint, text: copy.textHint, skill: copy.skillHint }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={headings[kind]}
      description={descriptions[kind]}
      closeLabel={copy.close}
      returnFocusRef={returnFocusRef}
      initialFocusRef={inputRef}
    >
      {kind === 'skill' ? (
        <SkillContextPicker
          copy={copy}
          client={skillClient}
          existing={existing}
          onAdd={onAdd}
          onClose={onClose}
          inputRef={inputRef}
        />
      ) : (
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault()
            const normalized = kind === 'link' ? normalizeContextUrl(value) : null
            if (kind === 'link' && !normalized) {
              setError(copy.invalidUrl)
              return
            }
            const reference: ContextReference =
              kind === 'link'
                ? {
                    id: crypto.randomUUID(),
                    kind: 'link',
                    title: title.trim() || new URL(normalized!).hostname,
                    url: normalized!,
                  }
                : { id: crypto.randomUUID(), kind: 'text', title: title.trim(), text: value.trim() }
            const result = onAdd(reference)
            setError(result)
            if (!result) onClose()
          }}
        >
          <div className="space-y-2">
            <label htmlFor={`${id}-title`} className="block text-sm font-medium">
              {kind === 'link' ? copy.optionalTitle : copy.title}
            </label>
            <input
              ref={inputRef}
              id={`${id}-title`}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={copy.titlePlaceholder}
              maxLength={MAX_CONTEXT_TITLE_LENGTH}
              required={kind === 'text'}
              aria-invalid={error === copy.invalidTitle}
              aria-describedby={error === copy.invalidTitle ? `${id}-error` : undefined}
              className={inputClass}
            />
          </div>
          <div className="space-y-2">
            <label htmlFor={`${id}-content`} className="block text-sm font-medium">
              {kind === 'link' ? copy.url : copy.text}
            </label>
            {kind === 'link' ? (
              <input
                id={`${id}-content`}
                inputMode="url"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value)
                  setError(null)
                }}
                maxLength={MAX_CONTEXT_URL_LENGTH}
                placeholder={copy.urlPlaceholder}
                required
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${id}-error` : undefined}
                className={inputClass}
              />
            ) : (
              <textarea
                id={`${id}-content`}
                value={value}
                onChange={(event) => {
                  setValue(event.target.value)
                  setError(null)
                }}
                maxLength={MAX_CONTEXT_TEXT_LENGTH}
                placeholder={copy.textPlaceholder}
                required
                aria-invalid={Boolean(error)}
                aria-describedby={`${id}-count${error ? ` ${id}-error` : ''}`}
                className={`${inputClass} min-h-32 max-h-[30dvh] resize-y leading-6`}
              />
            )}
            {kind === 'text' ? (
              <p id={`${id}-count`} className="text-right text-xs text-agent-muted">
                {value.length.toLocaleString()} / 12,000
              </p>
            ) : null}
          </div>
          {error ? (
            <p id={`${id}-error`} role="alert" className="text-xs leading-5 text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className={secondaryClass}>
              {copy.cancel}
            </button>
            <button
              type="submit"
              disabled={!value.trim() || (kind === 'text' && !title.trim())}
              className={primaryClass}
            >
              {copy.add}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
