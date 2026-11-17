import { Bookmark, FileText } from 'lucide-react'
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from 'react'

import { AnchoredPopover } from '../../components/ui/anchored-popover'
import { Button } from '../../components/ui/button'
import {
  keyboardIndex,
  markerProgress,
  MIN_NAVIGATION_ITEMS,
  MIN_RAIL_SPACE,
  type UserMessageNavigationItem,
  type UserMessagePreviewLoader,
} from './model'
import { useMessageNavigation, type MessageNavigationCallbacks } from './use-message-navigation'
import { useMessagePreview } from './use-message-preview'
import './user-message-navigation-rail.css'

export type UserMessageNavigationRailProps = MessageNavigationCallbacks & {
  items: readonly UserMessageNavigationItem[]
  activeId: string | null
  /** Several user messages may be visible at the same time. */
  activeIds?: readonly string[]
  onPreviewItem?: UserMessagePreviewLoader
  onBookmarkChange?: (item: UserMessageNavigationItem, bookmarked: boolean) => void | Promise<void>
  /** Space measured by the feature between the transcript and its container edge. */
  availableSpace?: number
  side?: 'left' | 'right'
  shortcutScopeRef?: RefObject<HTMLElement | null>
  className?: string
  labels?: {
    navigation?: string
    loading?: string
    unavailable?: string
    bookmark?: string
    removeBookmark?: string
    navigationError?: string
    bookmarkError?: string
    position?: (index: number, total: number) => string
  }
}

type PointerSession = { id: number; dragging: boolean; lastItemId: string | null }

export function UserMessageNavigationRail(props: UserMessageNavigationRailProps) {
  if (
    props.items.length < MIN_NAVIGATION_ITEMS ||
    (props.availableSpace ?? MIN_RAIL_SPACE) < MIN_RAIL_SPACE
  )
    return null
  // Unmount the interaction owner when hidden: previews, capture and requests must not survive it.
  return <UserMessageNavigationRailContent {...props} />
}

function UserMessageNavigationRailContent({
  items,
  activeId,
  activeIds,
  onNavigate,
  onRevealItem,
  onPreviewItem,
  onBookmarkChange,
  availableSpace = MIN_RAIL_SPACE,
  side = 'left',
  shortcutScopeRef,
  className,
  labels,
}: UserMessageNavigationRailProps) {
  const id = useId()
  const listRef = useRef<HTMLOListElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)
  const buttons = useRef(new Map<string, HTMLElement>())
  const pointer = useRef<PointerSession | null>(null)
  const suppressClick = useRef(false)
  const suppressFocusPreview = useRef(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const inRail = useRef(false)
  const inPreview = useRef(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [mode, setMode] = useState<'hover' | 'focus' | null>(null)
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const [scrubbing, setScrubbing] = useState(false)
  const [bookmarkPending, setBookmarkPending] = useState<string | null>(null)
  const [bookmarkError, setBookmarkError] = useState<string | null>(null)
  const mounted = useRef(true)
  const navigation = useMessageNavigation({ onNavigate, onRevealItem })
  const { busyId, cancel } = navigation
  const shown = items.length >= MIN_NAVIGATION_ITEMS && availableSpace >= MIN_RAIL_SPACE
  const selectedIndex = items.findIndex((item) => item.id === selectedId)
  if (selectedId !== null && selectedIndex < 0) {
    setSelectedId(null)
    setMode(null)
    setAnchor(null)
    setFocusedId(null)
  }
  const selected = shown && selectedIndex >= 0 ? items[selectedIndex] : null
  const open = selected !== null && !scrubbing
  const { preview, status } = useMessagePreview({
    item: open ? selected : null,
    mode,
    onPreviewItem,
  })
  const currentIds = new Set(activeIds ?? (activeId ? [activeId] : []))
  const tabStop = items.some((item) => item.id === focusedId)
    ? focusedId
    : items.some((item) => item.id === activeId)
      ? activeId
      : items[0]?.id
  const positionLabel =
    labels?.position ?? ((index: number, total: number) => `${index} / ${total}`)
  const navigationLabel = labels?.navigation ?? 'User message navigation'

  function clearCloseTimer() {
    clearTimeout(closeTimer.current)
  }
  function closePreview() {
    clearCloseTimer()
    inPreview.current = false
    setSelectedId(null)
    setMode(null)
  }
  function scheduleClose() {
    clearCloseTimer()
    closeTimer.current = setTimeout(() => {
      const focus = document.activeElement
      const keepsFocus =
        popupRef.current?.contains(focus) ||
        (mode === 'focus' && selectedId !== null && buttons.current.get(selectedId) === focus)
      if (!inRail.current && !inPreview.current && !keepsFocus && !pointer.current?.dragging)
        closePreview()
    }, 120)
  }
  function select(itemId: string, source: 'hover' | 'focus') {
    clearCloseTimer()
    setAnchor(buttons.current.get(itemId) ?? null)
    setSelectedId(itemId)
    setMode(source)
  }
  function keepMarkerVisible(itemId: string) {
    const list = listRef.current
    const button = buttons.current.get(itemId)
    if (!list || !button) return
    const viewport = list.getBoundingClientRect()
    const bounds = button.getBoundingClientRect()
    if (bounds.top < viewport.top) list.scrollTop -= viewport.top - bounds.top
    else if (bounds.bottom > viewport.bottom) list.scrollTop += bounds.bottom - viewport.bottom
  }
  function focusMarker(itemId: string, previewEnabled = true) {
    suppressFocusPreview.current = !previewEnabled
    buttons.current.get(itemId)?.focus({ preventScroll: true })
    suppressFocusPreview.current = false
    setFocusedId(itemId)
    keepMarkerVisible(itemId)
    if (previewEnabled) select(itemId, 'focus')
  }
  function dismissAndRestore() {
    const itemId = selectedId
    closePreview()
    if (itemId) focusMarker(itemId, false)
  }
  async function activate(item: UserMessageNavigationItem, source: 'click' | 'keyboard') {
    if (await navigation.navigate(item, source)) {
      // Do not close a different preview opened while history was loading.
      setSelectedId((current) => (current === item.id ? null : current))
    }
  }
  function handleKey(event: KeyboardEvent<HTMLElement>, index: number) {
    if (event.altKey || event.ctrlKey || event.metaKey) return
    if (event.key === 'Escape') {
      event.preventDefault()
      closePreview()
      return
    }
    if (event.key === 'ArrowRight' && onBookmarkChange) {
      event.preventDefault()
      select(items[index].id, 'focus')
      // The popup may still be mounting after a focus event.
      requestAnimationFrame(() =>
        popupRef.current?.querySelector<HTMLButtonElement>('button')?.focus(),
      )
      return
    }
    const next = keyboardIndex(event.key, index, items.length)
    if (next !== null) {
      event.preventDefault()
      focusMarker(items[next].id)
    }
  }
  function itemAtY(clientY: number) {
    const first = items[0] && buttons.current.get(items[0].id)
    if (!first) return null
    const bounds = first.getBoundingClientRect()
    if (!bounds.height) return null
    const viewport = listRef.current?.getBoundingClientRect()
    if (viewport && viewport.height > 0)
      clientY = Math.max(viewport.top, Math.min(viewport.bottom - 1, clientY))
    const index = Math.max(
      0,
      Math.min(items.length - 1, Math.floor((clientY - bounds.top) / bounds.height)),
    )
    return items[index]
  }
  function pointerMove(event: PointerEvent<HTMLOListElement>) {
    const session = pointer.current
    if (event.pointerType === 'touch' && !session) return
    const item = itemAtY(event.clientY)
    if (!item) return
    if (session && session.id === event.pointerId) {
      if ((event.buttons & 1) === 0) {
        endPointer(event, true)
        return
      }
      if (!session.dragging && item.id !== session.lastItemId) {
        session.dragging = true
        setScrubbing(true)
        event.currentTarget.setPointerCapture?.(event.pointerId)
      }
      if (session.dragging) {
        event.preventDefault()
        select(item.id, 'hover')
        if (session.lastItemId !== item.id) {
          session.lastItemId = item.id
          if (item.isLoaded !== false) void navigation.navigate(item, 'scrub')
        }
        return
      }
    }
    select(item.id, 'hover')
  }
  function endPointer(event: PointerEvent<HTMLOListElement>, cancelled = false) {
    const session = pointer.current
    if (!session || session.id !== event.pointerId) return
    pointer.current = null
    suppressClick.current = session.dragging || cancelled
    setScrubbing(false)
    if (cancelled && session.dragging) navigation.cancel()
    if (event.currentTarget.hasPointerCapture?.(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    if (session.dragging || cancelled) closePreview()
  }
  async function toggleBookmark(item: UserMessageNavigationItem) {
    if (!onBookmarkChange) return
    setBookmarkPending(item.id)
    setBookmarkError(null)
    try {
      await onBookmarkChange(item, !item.isBookmarked)
    } catch {
      if (mounted.current) setBookmarkError(item.id)
    } finally {
      if (mounted.current) setBookmarkPending((current) => (current === item.id ? null : current))
    }
  }

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      clearTimeout(closeTimer.current)
    }
  }, [])

  useLayoutEffect(() => {
    if (shown && activeId && !selectedId && !scrubbing) keepMarkerVisible(activeId)
  }, [shown, activeId, selectedId, scrubbing, items])

  useEffect(() => {
    if (busyId && !items.some((item) => item.id === busyId)) cancel()
  }, [items, busyId, cancel])

  const shortcutState = useRef({ items, activeId, navigate: navigation.navigate })
  useLayoutEffect(() => {
    shortcutState.current = { items, activeId, navigate: navigation.navigate }
  })
  useEffect(() => {
    const scope = shortcutScopeRef?.current
    if (!scope || !shown) return
    const handleShortcut = (event: globalThis.KeyboardEvent) => {
      if (
        !event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.isComposing ||
        event.defaultPrevented
      )
        return
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      const target = event.target
      if (
        target instanceof HTMLElement &&
        target.closest('input,textarea,select,[contenteditable="true"]')
      )
        return
      const current = shortcutState.current
      const index = current.items.findIndex((item) => item.id === current.activeId)
      const next = keyboardIndex(event.key, Math.max(0, index), current.items.length)
      if (next === null) return
      event.preventDefault()
      if (next !== index) void current.navigate(current.items[next], 'shortcut')
    }
    scope.addEventListener('keydown', handleShortcut)
    return () => scope.removeEventListener('keydown', handleShortcut)
  }, [shortcutScopeRef, shown])

  if (!shown) return null

  return (
    <nav
      className={`user-message-navigation-rail${className ? ` ${className}` : ''}`}
      aria-label={navigationLabel}
      data-side={side}
    >
      <ol
        ref={listRef}
        className="user-message-navigation-rail__list"
        data-floating-navigation-rail-list=""
        data-thread-user-message-navigation-rail-list=""
        data-scrubbing={scrubbing || undefined}
        onPointerEnter={() => {
          inRail.current = true
          clearCloseTimer()
        }}
        onPointerLeave={() => {
          inRail.current = false
          scheduleClose()
        }}
        onPointerDown={(event) => {
          if (event.pointerType === 'touch') {
            suppressClick.current = false
            return
          }
          if (event.button !== 0 || !event.isPrimary) return
          suppressClick.current = false
          pointer.current = {
            id: event.pointerId,
            dragging: false,
            lastItemId: itemAtY(event.clientY)?.id ?? null,
          }
        }}
        onPointerMove={pointerMove}
        onPointerUp={(event) => endPointer(event)}
        onPointerCancel={(event) => endPointer(event, true)}
        onLostPointerCapture={(event) => endPointer(event, true)}
        onScroll={() => {
          if (mode === 'hover' && !scrubbing) closePreview()
        }}
      >
        {items.map((item, index) => {
          const targeted = selected?.id === item.id
          const progress = markerProgress(index, selected ? selectedIndex : null)
          return (
            <li key={item.id}>
              <Button
                variant="ghost"
                ref={(element: HTMLElement | null) => {
                  if (element) buttons.current.set(item.id, element)
                  else buttons.current.delete(item.id)
                }}
                className="user-message-navigation-rail__button"
                data-item-id={item.id}
                data-thread-user-message-navigation-item-id={item.id}
                data-scrub-target={targeted || undefined}
                data-unloaded={item.isLoaded === false || undefined}
                aria-label={`${positionLabel(index + 1, items.length)}: ${item.getLabel()}`}
                aria-current={currentIds.has(item.id) ? 'true' : undefined}
                aria-busy={navigation.busyId === item.id || undefined}
                aria-haspopup={onBookmarkChange ? 'dialog' : undefined}
                aria-expanded={onBookmarkChange ? targeted && open : undefined}
                aria-controls={targeted && open && onBookmarkChange ? `${id}-preview` : undefined}
                aria-describedby={
                  targeted && open && !onBookmarkChange ? `${id}-preview` : undefined
                }
                tabIndex={item.id === tabStop ? 0 : -1}
                onFocus={(event) => {
                  setFocusedId(item.id)
                  if (
                    !suppressFocusPreview.current &&
                    event.currentTarget.matches(':focus-visible')
                  )
                    select(item.id, 'focus')
                }}
                onBlur={(event) => {
                  if (
                    !listRef.current?.contains(event.relatedTarget) &&
                    !popupRef.current?.contains(event.relatedTarget)
                  ) {
                    setFocusedId(null)
                    scheduleClose()
                  }
                }}
                onKeyDown={(event) => handleKey(event, index)}
                onClick={(event) => {
                  if (event.detail > 0 && suppressClick.current) {
                    suppressClick.current = false
                    return
                  }
                  void activate(item, event.detail === 0 ? 'keyboard' : 'click')
                }}
              >
                <span
                  aria-hidden="true"
                  className="user-message-navigation-rail__marker"
                  data-bookmarked={item.isBookmarked || undefined}
                  style={{ '--marker-progress': progress } as CSSProperties}
                />
              </Button>
            </li>
          )
        })}
      </ol>
      {selected ? (
        <AnchoredPopover
          ref={popupRef}
          open={open}
          anchor={anchor}
          side={side === 'left' ? 'right' : 'left'}
          id={`${id}-preview`}
          role={onBookmarkChange ? 'dialog' : 'tooltip'}
          aria-label={onBookmarkChange ? selected.getLabel() : undefined}
          onOpenChange={(next) => {
            if (!next) closePreview()
          }}
          onPointerEnter={() => {
            inPreview.current = true
            clearCloseTimer()
          }}
          onPointerLeave={() => {
            inPreview.current = false
            scheduleClose()
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              event.stopPropagation()
              dismissAndRestore()
            }
          }}
          onBlur={(event) => {
            if (
              !event.currentTarget.contains(event.relatedTarget) &&
              !listRef.current?.contains(event.relatedTarget)
            )
              scheduleClose()
          }}
        >
          <div
            className="user-message-navigation-rail__preview"
            data-thread-user-message-navigation-tooltip-preview=""
          >
            <div className="user-message-navigation-rail__preview-header">
              <p className="user-message-navigation-rail__label">{selected.getLabel()}</p>
              {onBookmarkChange ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="user-message-navigation-rail__bookmark"
                  aria-label={
                    selected.isBookmarked
                      ? (labels?.removeBookmark ?? 'Remove bookmark')
                      : (labels?.bookmark ?? 'Bookmark message')
                  }
                  aria-pressed={Boolean(selected.isBookmarked)}
                  disabled={bookmarkPending === selected.id}
                  onClick={() => void toggleBookmark(selected)}
                >
                  <Bookmark
                    size={15}
                    fill={selected.isBookmarked ? 'currentColor' : 'none'}
                    aria-hidden="true"
                  />
                </Button>
              ) : null}
            </div>
            {status === 'loading' ? (
              <p role="status" className="user-message-navigation-rail__status">
                {labels?.loading ?? 'Loading preview…'}
              </p>
            ) : status === 'unavailable' ? (
              <p className="user-message-navigation-rail__status">
                {labels?.unavailable ?? 'Preview unavailable'}
              </p>
            ) : preview?.response ? (
              <p className="user-message-navigation-rail__response">{preview.response}</p>
            ) : null}
            {status === 'loaded' && Boolean(preview?.outputs?.length) ? (
              <div className="user-message-navigation-rail__outputs">
                {preview!.outputs!.slice(0, 2).map((output) => (
                  <span
                    key={output.id}
                    className="user-message-navigation-rail__output"
                    title={output.label}
                  >
                    <FileText size={12} aria-hidden="true" />
                    <span>{output.label}</span>
                  </span>
                ))}
                {preview!.outputs!.length > 2 ? (
                  <span className="user-message-navigation-rail__more">
                    +{preview!.outputs!.length - 2}
                  </span>
                ) : null}
              </div>
            ) : null}
            {bookmarkError === selected.id ? (
              <p role="alert">{labels?.bookmarkError ?? 'Could not save the bookmark.'}</p>
            ) : null}
            {navigation.errorId === selected.id ? (
              <p role="alert">{labels?.navigationError ?? 'Could not navigate to this message.'}</p>
            ) : null}
          </div>
        </AnchoredPopover>
      ) : null}
      <span className="sr-only" role="status">
        {navigation.errorId && navigation.errorId !== selectedId
          ? (labels?.navigationError ?? 'Could not navigate to this message.')
          : null}
      </span>
    </nav>
  )
}
