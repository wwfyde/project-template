import { Link } from '@tanstack/react-router'
import {
  ArrowUpRight,
  Box,
  ChevronRight,
  CircleDashed,
  FolderOpen,
  MessageCircle,
  PanelLeftClose,
  Search,
  SquarePen,
  Workflow,
  X,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { IconButton } from '../../../components/ui/icon-button'
import type { AgentCopy } from '../model/translations'
import type { Conversation } from '../model/workspace'

type AgentSidebarProps = {
  copy: AgentCopy
  conversations: Conversation[]
  activeId?: string
  userName: string
  onNew: () => void
  onSelect: (id: string) => void
  onClose?: () => void
}

export function AgentSidebar({ copy, conversations, activeId, userName, onNew, onSelect, onClose }: AgentSidebarProps) {
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const searchTriggerRef = useRef<HTMLButtonElement>(null)
  const closeSearch = () => {
    setSearching(false)
    setQuery('')
    searchTriggerRef.current?.focus()
  }
  const filtered = [...conversations]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .filter((conversation) => conversation.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const navClass = 'agent-nav-item'

  return (
    <div className="flex h-full min-h-0 flex-col bg-agent-sidebar px-3 pb-3 pt-4 text-agent-text">
      <div className="mb-7 flex h-10 items-center justify-between px-2">
        <Link
          to="/"
          aria-label={copy.back}
          className="flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-agent-muted"
        >
          <span className="flex size-8 items-center justify-center rounded-[10px] bg-agent-strong text-agent-on-strong">
            <Box size={19} strokeWidth={1.6} />
          </span>
          <span className="text-[17px] font-semibold tracking-tight">
            workspace<span className="text-agent-muted">.</span>
          </span>
        </Link>
        {onClose ? (
          <IconButton label={copy.closeSidebar} onClick={onClose} className="size-8">
            <PanelLeftClose size={18} strokeWidth={1.7} />
          </IconButton>
        ) : null}
      </div>

      <nav aria-label={copy.workspace} className="space-y-1">
        <button type="button" onClick={onNew} className={`${navClass} font-medium`}>
          <SquarePen size={18} strokeWidth={1.7} />
          <span>{copy.newChat}</span>
          <span className="ml-auto text-[11px] text-agent-muted">⌘ K</span>
        </button>
        <button
          ref={searchTriggerRef}
          type="button"
          onClick={() => {
            setSearching(true)
            requestAnimationFrame(() => searchRef.current?.focus())
          }}
          className={navClass}
        >
          <Search size={18} strokeWidth={1.7} />
          {copy.search}
        </button>
        <Link to="/assets" className={navClass}>
          <FolderOpen size={18} strokeWidth={1.7} />
          {copy.assets}
          <ArrowUpRight size={14} className="ml-auto text-agent-muted" />
        </Link>
        <Link to="/skills" className={navClass}>
          <CircleDashed size={18} strokeWidth={1.7} />
          {copy.skills}
          <ArrowUpRight size={14} className="ml-auto text-agent-muted" />
        </Link>
      </nav>

      {searching ? (
        <div className="relative mx-1 mt-5">
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={copy.searchPlaceholder}
            aria-label={copy.search}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.stopPropagation()
                closeSearch()
              }
            }}
            className="w-full rounded-lg border border-agent-border bg-agent-surface py-2 pl-3 pr-9 text-sm outline-none focus:border-agent-muted"
          />
          <button
            type="button"
            aria-label={copy.closeSearch}
            onClick={closeSearch}
            className="absolute right-1 top-1 flex size-7 items-center justify-center rounded-md text-agent-muted hover:bg-agent-subtle"
          >
            <X size={14} />
          </button>
        </div>
      ) : null}

      <div className="mt-8 min-h-0 flex-1 overflow-y-auto">
        {[false, true].map((examples) => {
          const rows = filtered.filter((item) => Boolean(item.isExample) === examples)
          if (!rows.length) return null
          return (
            <section key={String(examples)} className="mb-6">
              <h2 className="mb-2 px-3 text-[11px] font-medium text-agent-muted">
                {examples ? copy.examples : copy.conversations}
              </h2>
              {rows.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  onClick={() => onSelect(conversation.id)}
                  aria-current={activeId === conversation.id ? 'page' : undefined}
                  className={`agent-nav-item group w-full text-left ${activeId === conversation.id ? 'bg-agent-subtle' : ''}`}
                >
                  {conversation.mode === 'chat' ? (
                    <MessageCircle size={15} className="shrink-0 text-agent-muted" />
                  ) : (
                    <Workflow size={15} className="shrink-0 text-agent-muted" />
                  )}
                  <span className="truncate text-[13px]">{conversation.title}</span>
                </button>
              ))}
            </section>
          )
        })}
        {query && !filtered.length ? <p className="px-3 text-xs text-agent-muted">{copy.noResults}</p> : null}
      </div>

      <div className="mx-2 mb-4 rounded-xl border border-agent-border px-3 py-3.5">
        <div className="mb-1.5 flex items-center gap-2 text-xs font-medium">
          <span className="size-1.5 rounded-full bg-agent-success" />
          {copy.preview}
        </div>
        <p className="text-[11px] leading-[1.7] text-agent-muted">{copy.localHint}</p>
      </div>
      <Link to="/account" aria-label={copy.account} className={`${navClass} py-2`}>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-agent-subtle text-xs font-medium">
          {userName.slice(0, 2).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">{userName}</p>
          <p className="mt-0.5 text-[10px] text-agent-muted">{copy.workspace}</p>
        </div>
        <ChevronRight size={14} className="text-agent-muted" />
      </Link>
    </div>
  )
}
