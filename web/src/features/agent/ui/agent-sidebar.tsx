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
    <div data-agent-scope="" className="flex h-full min-h-0 flex-col bg-sidebar px-3 pb-3 pt-4 text-sidebar-foreground">
      <div className="mb-7 flex h-10 items-center justify-between px-2">
        <Link
          to="/"
          aria-label={copy.back}
          className="flex items-center gap-2.5 rounded-control focus-visible:outline-2 focus-visible:outline-ring"
        >
          <span className="flex size-8 items-center justify-center rounded-control bg-primary text-primary-foreground">
            <Box size={19} strokeWidth={1.6} />
          </span>
          <span className="text-[17px] font-semibold tracking-tight">
            workspace<span className="text-muted-foreground">.</span>
          </span>
        </Link>
        {onClose ? (
          <IconButton label={copy.closeSidebar} onClick={onClose} size="sm">
            <PanelLeftClose size={18} strokeWidth={1.7} />
          </IconButton>
        ) : null}
      </div>

      <nav aria-label={copy.workspace} className="space-y-1">
        <button type="button" onClick={onNew} className={`${navClass} font-medium`}>
          <SquarePen size={18} strokeWidth={1.7} />
          <span>{copy.newChat}</span>
          <span className="ml-auto text-[11px] text-muted-foreground">⌘ K</span>
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
          <ArrowUpRight size={14} className="ml-auto text-muted-foreground" />
        </Link>
        <Link to="/skills" className={navClass}>
          <CircleDashed size={18} strokeWidth={1.7} />
          {copy.skills}
          <ArrowUpRight size={14} className="ml-auto text-muted-foreground" />
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
            className="min-h-control w-full rounded-control border border-input bg-background py-2 pl-3 pr-9 text-sm shadow-control outline-none focus:border-ring focus:ring-1 focus:ring-ring"
          />
          <button
            type="button"
            aria-label={copy.closeSearch}
            onClick={closeSearch}
            className="absolute right-1 top-1 flex size-7 items-center justify-center rounded-control text-muted-foreground hover:bg-accent"
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
              <h2 className="mb-2 px-3 text-[11px] font-medium text-muted-foreground">
                {examples ? copy.examples : copy.conversations}
              </h2>
              {rows.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  onClick={() => onSelect(conversation.id)}
                  aria-current={activeId === conversation.id ? 'page' : undefined}
                  className={`agent-nav-item group w-full text-left ${activeId === conversation.id ? 'bg-accent text-accent-foreground' : ''}`}
                >
                  {conversation.mode === 'chat' ? (
                    <MessageCircle size={15} className="shrink-0 text-muted-foreground" />
                  ) : (
                    <Workflow size={15} className="shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate text-[13px]">{conversation.title}</span>
                </button>
              ))}
            </section>
          )
        })}
        {query && !filtered.length ? <p className="px-3 text-xs text-muted-foreground">{copy.noResults}</p> : null}
      </div>

      <div className="mx-2 mb-4 rounded-panel border border-border px-3 py-3.5">
        <div className="mb-1.5 flex items-center gap-2 text-xs font-medium">
          <span className="size-1.5 rounded-full bg-success" />
          {copy.preview}
        </div>
        <p className="text-[11px] leading-[1.7] text-muted-foreground">{copy.localHint}</p>
      </div>
      <Link to="/account" aria-label={copy.account} className={`${navClass} py-2`}>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
          {userName.slice(0, 2).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">{userName}</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">{copy.workspace}</p>
        </div>
        <ChevronRight size={14} className="text-muted-foreground" />
      </Link>
    </div>
  )
}
