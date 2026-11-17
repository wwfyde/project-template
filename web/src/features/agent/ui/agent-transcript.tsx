import {
  ArrowDown,
  Check,
  CheckCheck,
  Circle,
  Copy,
  FileText,
  LoaderCircle,
  Sparkles,
  Square,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { UserMessageNavigationRail } from '../../../blocks/user-message-navigation-rail'
import { IconButton } from '../../../components/ui/icon-button'
import { useMessageBookmarks } from '../../user-message-navigation/ui/use-message-bookmarks'
import { useUserMessageNavigation } from '../../user-message-navigation/ui/use-user-message-navigation'
import type { AgentCopy } from '../model/translations'
import type { AgentActionsCopy } from '../model/action-translations'
import type { Conversation } from '../model/workspace'
import { userMessageNavigationItems } from '../model/navigation'
import { ContextReferenceList } from './context-reference-list'

export function AgentTranscript({
  conversation,
  copy,
  contextCopy,
}: {
  conversation: Conversation
  copy: AgentCopy
  contextCopy: AgentActionsCopy
}) {
  const followLatest = useRef(true)
  const [awayFromBottom, setAwayFromBottom] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [copyError, setCopyError] = useState(false)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const messages = conversation.messages
  const questions = useMemo(() => messages.filter((message) => message.role === 'user'), [messages])
  const questionIds = useMemo(() => questions.map((question) => question.id), [questions])
  const { bookmarkedIds, setBookmarked } = useMessageBookmarks(`agent:${conversation.id}`)
  const items = useMemo(
    () => userMessageNavigationItems(messages, bookmarkedIds),
    [messages, bookmarkedIds],
  )
  const {
    frameRef,
    scrollRef,
    contentRef,
    activeId,
    activeIds,
    availableSpace,
    railOffset,
    highlightedId,
    registerMessage,
    navigateTo,
    isNavigationPending,
    cancelNavigation,
  } = useUserMessageNavigation(questionIds, conversation.id, () => {
    followLatest.current = false
  })
  const latest = messages.at(-1)

  const scrollToLatest = () => {
    const node = scrollRef.current
    if (!node) return
    cancelNavigation()
    node.scrollTop = node.scrollHeight
    followLatest.current = true
    setAwayFromBottom(false)
  }

  useEffect(() => {
    followLatest.current = true
    scrollToLatest()
    // A newly selected conversation starts at its latest turn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.id])

  useEffect(() => {
    if (followLatest.current) scrollToLatest()
    // Only new transcript content should move the scroll position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latest?.content, latest?.status, messages.length])

  useEffect(() => () => clearTimeout(copyTimer.current), [])

  const copyMessage = async (id: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      setCopiedId(id)
      setCopyError(false)
      clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => setCopiedId(null), 1800)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <div ref={frameRef} className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        className="agent-transcript h-full overflow-y-auto px-5 sm:px-10"
        role="region"
        aria-label={conversation.title}
        tabIndex={0}
        onScroll={() => {
          const node = scrollRef.current
          if (!node) return
          const away = node.scrollHeight - node.clientHeight - node.scrollTop > 100
          if (!isNavigationPending()) followLatest.current = !away
          setAwayFromBottom(away)
        }}
      >
        <div ref={contentRef} className="mx-auto max-w-[760px] space-y-7 pb-10 pt-9 sm:pt-12">
          {messages.map((message) => (
            <article
              key={message.id}
              className="agent-message"
              aria-label={message.role === 'user' ? copy.user : copy.assistant}
            >
              {message.role === 'user' ? (
                <div className="ml-auto max-w-[88%] sm:max-w-[82%]">
                  {Boolean(message.contexts?.length) && (
                    <ContextReferenceList items={message.contexts!} copy={contextCopy} />
                  )}
                  {Boolean(message.attachments?.length) && (
                    <div className="mb-2 flex flex-wrap justify-end gap-2">
                      {message.attachments?.map((file) => (
                        <span
                          key={file.id}
                          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-agent-border px-3 py-2 text-xs text-agent-muted"
                        >
                          <FileText size={15} className="shrink-0" />
                          <span className="truncate">{file.name}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  <div
                    ref={(node) => registerMessage(message.id, node)}
                    data-user-message-bubble=""
                    data-navigation-highlight={message.id === highlightedId || undefined}
                    className="w-fit rounded-[22px] bg-agent-subtle px-5 py-3 text-[15px] leading-7 whitespace-pre-wrap ml-auto"
                  >
                    {message.content}
                  </div>
                </div>
              ) : (
                <div>
                  <div className="mb-4 flex items-center gap-2.5">
                    <span className="flex size-7 items-center justify-center rounded-full border border-agent-border">
                      <Sparkles size={15} strokeWidth={1.6} />
                    </span>
                    <span className="text-[13px] font-semibold">Agent</span>
                    <span className="rounded-md border border-agent-border px-1.5 py-0.5 text-[10px] text-agent-muted">
                      {copy.example}
                    </span>
                    <span
                      role="status"
                      className={
                        message.status === 'completed'
                          ? 'sr-only'
                          : 'ml-auto text-[11px] text-agent-muted'
                      }
                    >
                      {message.status === 'running'
                        ? copy.running
                        : message.status === 'cancelled'
                          ? copy.cancelled
                          : message.status === 'error'
                            ? copy.error
                            : copy.completed}
                    </span>
                  </div>
                  {message.steps ? (
                    <div className="mb-5 overflow-hidden rounded-2xl border border-agent-border">
                      <div className="flex items-center justify-between border-b border-agent-border px-4 py-3 text-xs">
                        <span className="font-medium">{copy.taskPlan}</span>
                        <span className="text-agent-muted">
                          {message.steps.filter((step) => step.status === 'completed').length} /{' '}
                          {message.steps.length}
                        </span>
                      </div>
                      <ol className="space-y-3.5 px-4 py-4">
                        {message.steps.map((step) => {
                          const cancelled =
                            message.status === 'cancelled' && step.status === 'running'
                          const StepIcon =
                            step.status === 'completed'
                              ? Check
                              : cancelled
                                ? Square
                                : step.status === 'running'
                                  ? LoaderCircle
                                  : Circle
                          return (
                            <li key={step.id} className="flex items-center gap-3 text-[13px]">
                              <StepIcon
                                size={15}
                                className={`${step.status === 'completed' ? 'text-agent-success' : 'text-agent-muted'} ${step.status === 'running' && !cancelled ? 'animate-spin' : ''}`}
                              />
                              <span className="flex-1">{step.label}</span>
                              <span className="text-[11px] text-agent-muted">
                                {step.status === 'completed'
                                  ? copy.completed
                                  : cancelled
                                    ? copy.cancelled
                                    : step.status === 'running'
                                      ? copy.stepRunning
                                      : copy.pending}
                              </span>
                            </li>
                          )
                        })}
                      </ol>
                    </div>
                  ) : null}
                  <div className="text-[15px] leading-[1.85] whitespace-pre-wrap">
                    {message.content ||
                      (message.status === 'cancelled' ? copy.stoppedResponse : copy.emptyResponse)}
                    {message.status === 'running' ? (
                      <span
                        aria-hidden="true"
                        className="ml-1 inline-block size-2 animate-pulse rounded-full bg-agent-text"
                      />
                    ) : null}
                  </div>
                  {message.status !== 'running' && message.content ? (
                    <div className="mt-3 flex items-center gap-2">
                      <IconButton
                        label={copiedId === message.id ? copy.copied : copy.copy}
                        onClick={() => void copyMessage(message.id, message.content)}
                        className="size-8 text-agent-muted"
                      >
                        {copiedId === message.id ? (
                          <CheckCheck size={15} />
                        ) : (
                          <Copy size={15} strokeWidth={1.6} />
                        )}
                      </IconButton>
                      {copiedId === message.id ? (
                        <span role="status" className="text-xs text-agent-muted">
                          {copy.copied}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )}
            </article>
          ))}
          {copyError ? (
            <p role="alert" className="text-xs text-agent-muted">
              {copy.copyFailed}
            </p>
          ) : null}
        </div>
      </div>
      {availableSpace >= 48 ? (
        <div
          className="agent-conversation-rail absolute top-1/2 -translate-y-1/2"
          style={{ left: railOffset }}
        >
          <UserMessageNavigationRail
            items={items}
            activeId={activeId}
            activeIds={activeIds}
            onNavigate={navigateTo}
            onBookmarkChange={(item, bookmarked) =>
              setBookmarked(item.bookmarkId ?? item.id, bookmarked)
            }
            availableSpace={availableSpace}
            shortcutScopeRef={frameRef}
            labels={copy.rail}
          />
        </div>
      ) : null}
      {awayFromBottom ? (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2">
          <IconButton
            label={copy.latest}
            onClick={scrollToLatest}
            className="border border-agent-border bg-agent-surface shadow-sm"
          >
            <ArrowDown size={18} />
          </IconButton>
        </div>
      ) : null}
    </div>
  )
}
