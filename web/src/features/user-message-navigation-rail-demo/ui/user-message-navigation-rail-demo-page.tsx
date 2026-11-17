import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, History, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  UserMessageNavigationRail,
  type UserMessageNavigationItem,
} from '../../../blocks/user-message-navigation-rail'
import { Button } from '../../../components/ui/button'
import { useMessageBookmarks } from '../../user-message-navigation/ui/use-message-bookmarks'
import { useUserMessageNavigation } from '../../user-message-navigation/ui/use-user-message-navigation'
import { createDemoConversation } from '../model/conversation'
import { fixturePreview, waitForFixture, HIDDEN_HISTORY_COUNT } from '../model/history-fixture'
import { railDemoEn, railDemoZhCN } from '../model/translations'
import './user-message-navigation-rail-demo.css'

export function UserMessageNavigationRailDemoPage() {
  const { i18n } = useTranslation()
  const language = i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en'
  const copy = language === 'zh-CN' ? railDemoZhCN : railDemoEn
  const [additionalTurns, setAdditionalTurns] = useState(0)
  const [revealedIds, setRevealedIds] = useState<ReadonlySet<string>>(() => new Set())
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const revealSequence = useRef(0)
  const manualNavigation = useRef<AbortController | null>(null)
  useEffect(() => () => manualNavigation.current?.abort(), [])
  const turns = useMemo(
    () => createDemoConversation(language, additionalTurns),
    [language, additionalTurns],
  )
  const ids = useMemo(() => turns.map((turn) => turn.id), [turns])
  const { bookmarkedIds, setBookmarked } = useMessageBookmarks('demo:user-message-navigation-rail')
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
    waitForMessage,
    navigateTo,
  } = useUserMessageNavigation(ids, 'demo:user-message-navigation-rail')
  const items = useMemo<UserMessageNavigationItem[]>(
    () =>
      turns.map((turn, index) => {
        const isLoaded = index >= HIDDEN_HISTORY_COUNT || revealedIds.has(turn.id)
        return {
          id: turn.id,
          turnKey: turn.id,
          bookmarkId: turn.id,
          getLabel: () => turn.question,
          getPreview: () => (isLoaded ? fixturePreview(turn, index, language) : undefined),
          isLoaded,
          isBookmarked: bookmarkedIds.has(turn.id),
          previewState: isLoaded ? 'loaded' : undefined,
        }
      }),
    [turns, language, revealedIds, bookmarkedIds],
  )
  const hiddenCount = items.filter((item) => !item.isLoaded).length

  const revealItem = useCallback(
    async (item: UserMessageNavigationItem, { signal }: { signal: AbortSignal }) => {
      if (signal.aborted) return false
      const sequence = ++revealSequence.current
      setLoadingHistory(true)
      setHistoryError(false)
      try {
        // This delay represents a documented local fixture, never a network request.
        if (!(await waitForFixture(350, signal))) return false
        setRevealedIds((current) => new Set([...current, item.id]))
        return await waitForMessage(item.id, signal)
      } finally {
        if (revealSequence.current === sequence) setLoadingHistory(false)
      }
    },
    [waitForMessage],
  )

  const loadPreview = useCallback(
    async (item: UserMessageNavigationItem, { signal }: { signal: AbortSignal }) => {
      if (!(await waitForFixture(280, signal))) return null
      const index = turns.findIndex((turn) => turn.id === item.id)
      // The second historical question intentionally demonstrates an unavailable preview.
      if (index < 0 || index === 1) return null
      return fixturePreview(turns[index], index, language)
    },
    [turns, language],
  )

  const openHistory = async () => {
    manualNavigation.current?.abort()
    const controller = new AbortController()
    manualNavigation.current = controller
    const target = items.find((item) => !item.isLoaded)
    if (!target) return
    try {
      if (await revealItem(target, { signal: controller.signal })) {
        await navigateTo(target.id, {
          source: 'click',
          behavior: 'instant',
          signal: controller.signal,
        })
      }
    } catch {
      setHistoryError(true)
    }
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{copy.title}</h1>
        <p className="text-muted-foreground">{copy.description}</p>
      </header>
      <div className="user-message-rail-demo rounded-lg border border-border bg-card text-card-foreground">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border p-4 sm:px-6">
          <div className="min-w-0 space-y-1">
            <p className="text-xs font-medium text-muted-foreground">
              {copy.demo} · {copy.turns(turns.length)}
            </p>
            <h2 className="font-semibold">{copy.conversationTitle}</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setAdditionalTurns((count) => count + 1)}
            >
              <Plus size={15} aria-hidden="true" />
              {copy.addTurn}
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => {
                manualNavigation.current?.abort()
                const controller = new AbortController()
                manualNavigation.current = controller
                void navigateTo(ids.at(-1)!, {
                  source: 'click',
                  behavior: 'smooth',
                  signal: controller.signal,
                }).catch(() => setHistoryError(true))
              }}
            >
              <ArrowDown size={15} aria-hidden="true" />
              {copy.latest}
            </Button>
          </div>
        </div>
        <div className="border-b border-border px-4 py-3 text-xs leading-relaxed text-muted-foreground sm:px-6">
          <p>{copy.fixtureDescription}</p>
          <p>{copy.hiddenHistory(hiddenCount)}</p>
        </div>
        <div ref={frameRef} className="user-message-rail-demo-body">
          <div
            ref={scrollRef}
            role="region"
            aria-label={copy.conversationLabel}
            tabIndex={0}
            className="user-message-rail-demo-scroll"
          >
            <div ref={contentRef} className="user-message-rail-demo-messages">
              {hiddenCount > 0 ? (
                <Button
                  variant="outline"
                  className="mb-6 min-h-11"
                  disabled={loadingHistory}
                  onClick={() => void openHistory()}
                >
                  <History size={15} aria-hidden="true" />
                  {loadingHistory ? copy.loadingHistory : copy.openHistory}
                </Button>
              ) : null}
              {turns.map((turn, index) =>
                items[index].isLoaded ? (
                  <article
                    key={turn.id}
                    aria-labelledby={`${turn.id}-question`}
                    className="user-message-rail-demo-turn"
                  >
                    <p className="mb-3 text-xs text-muted-foreground">{copy.turn(index + 1)}</p>
                    <div
                      ref={(element) => registerMessage(turn.id, element)}
                      data-user-message-bubble=""
                      data-navigation-highlight={turn.id === highlightedId || undefined}
                      className="user-message-rail-demo-question"
                    >
                      <p className="mb-2 text-xs font-medium text-muted-foreground">{copy.user}</p>
                      <h3 id={`${turn.id}-question`} className="font-medium leading-relaxed">
                        {turn.question}
                      </h3>
                    </div>
                    <div className="py-6">
                      <p className="mb-2 text-xs font-medium text-muted-foreground">
                        {copy.assistant}
                      </p>
                      <p className="leading-7">{turn.answer}</p>
                      {fixturePreview(turn, index, language).outputs?.length ? (
                        <p className="mt-3 text-xs text-muted-foreground">{copy.fixtureOutputs}</p>
                      ) : null}
                    </div>
                  </article>
                ) : null,
              )}
            </div>
          </div>
          {availableSpace >= 48 ? (
            <div className="user-message-rail-demo-navigation" style={{ left: railOffset }}>
              <UserMessageNavigationRail
                items={items}
                activeId={activeId}
                activeIds={activeIds}
                onNavigate={(id, options) => {
                  manualNavigation.current?.abort()
                  return navigateTo(id, options)
                }}
                onRevealItem={(item, options) => {
                  manualNavigation.current?.abort()
                  return revealItem(item, options)
                }}
                onPreviewItem={loadPreview}
                onBookmarkChange={(item, bookmarked) =>
                  setBookmarked(item.bookmarkId ?? item.id, bookmarked)
                }
                availableSpace={availableSpace}
                shortcutScopeRef={frameRef}
                labels={copy.rail}
              />
            </div>
          ) : null}
        </div>
        <div className="space-y-1 border-t border-border px-4 py-3 text-xs leading-relaxed text-muted-foreground sm:px-6">
          <p>{copy.hint}</p>
          <p role="status">
            {loadingHistory
              ? copy.loadingHistory
              : additionalTurns > 0
                ? copy.appended(additionalTurns)
                : null}
          </p>
          {historyError ? <p role="alert">{copy.rail.navigationError}</p> : null}
        </div>
      </div>
    </section>
  )
}
