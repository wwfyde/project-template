import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { UserMessageNavigationOptions } from '../../../blocks/user-message-navigation-rail'

/** Transcript DOM, reading position and scroll ownership stay outside the reusable rail. */
export function useUserMessageNavigation(
  ids: readonly string[],
  conversationId: string,
  onBeforeNavigate?: () => void,
) {
  const frameRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const messages = useRef(new Map<string, HTMLElement>())
  const scheduleMeasurement = useRef<() => void>(() => {})
  const beforeNavigate = useRef(onBeforeNavigate)
  useLayoutEffect(() => {
    beforeNavigate.current = onBeforeNavigate
  }, [onBeforeNavigate])
  const pendingNavigation = useRef<AbortController | null>(null)
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [activeIds, setActiveIds] = useState<readonly string[]>([])
  const [availableSpace, setAvailableSpace] = useState(0)
  const [highlightedId, setHighlightedId] = useState<string | null>(null)

  useEffect(() => {
    const frame = frameRef.current
    const scroll = scrollRef.current
    const content = contentRef.current
    if (!frame || !scroll || !content) return
    let request: number | null = null

    const measure = () => {
      request = null
      const viewport = scroll.getBoundingClientRect()
      const gutter = content.getBoundingClientRect().left - frame.getBoundingClientRect().left
      setAvailableSpace(Math.max(0, Math.floor(gutter)))
      const visible: string[] = []
      let current: string | null = null
      let firstLoaded: string | null = null
      let lastLoaded: string | null = null
      for (const id of ids) {
        const message = messages.current.get(id)
        if (!message?.isConnected || !content.contains(message)) continue
        firstLoaded ??= id
        lastLoaded = id
        const bounds = message.getBoundingClientRect()
        if (bounds.height > 0 && bounds.bottom > viewport.top && bounds.top < viewport.bottom) {
          visible.push(id)
        }
        if (bounds.top <= viewport.top + 48) current = id
      }
      const atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight <= 2
      setActiveId(atBottom ? lastLoaded : (current ?? firstLoaded))
      setActiveIds((previous) =>
        previous.length === visible.length && previous.every((id, index) => id === visible[index])
          ? previous
          : visible,
      )
    }
    const schedule = () => {
      if (request === null) request = requestAnimationFrame(measure)
    }
    scheduleMeasurement.current = schedule
    scroll.addEventListener('scroll', schedule, { passive: true })
    const resize = new ResizeObserver(schedule)
    resize.observe(frame)
    resize.observe(scroll)
    resize.observe(content)
    const mutation = new MutationObserver(schedule)
    mutation.observe(content, { childList: true, subtree: true, characterData: true })
    schedule()

    return () => {
      scheduleMeasurement.current = () => {}
      scroll.removeEventListener('scroll', schedule)
      resize.disconnect()
      mutation.disconnect()
      if (request !== null) cancelAnimationFrame(request)
    }
  }, [ids, conversationId])

  useEffect(
    () => () => {
      pendingNavigation.current?.abort()
      if (highlightTimer.current !== null) clearTimeout(highlightTimer.current)
    },
    [conversationId],
  )

  const registerMessage = useCallback((id: string, element: HTMLElement | null) => {
    if (element) messages.current.set(id, element)
    else messages.current.delete(id)
    scheduleMeasurement.current()
  }, [])

  const waitForMessage = useCallback(async (id: string, signal: AbortSignal) => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (signal.aborted) return false
      if (messages.current.get(id)?.isConnected) return true
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    }
    return false
  }, [])

  const isNavigationPending = useCallback(() => pendingNavigation.current !== null, [])
  const cancelNavigation = useCallback(() => {
    pendingNavigation.current?.abort()
    if (highlightTimer.current !== null) clearTimeout(highlightTimer.current)
    setHighlightedId(null)
  }, [])

  const navigateTo = useCallback(async (id: string, options: UserMessageNavigationOptions) => {
    pendingNavigation.current?.abort()
    if (highlightTimer.current !== null) clearTimeout(highlightTimer.current)
    setHighlightedId(null)
    if (options.signal.aborted) return
    const scroll = scrollRef.current
    const message = messages.current.get(id)
    if (!scroll || !message?.isConnected)
      throw new Error('The requested user message is not mounted.')

    const controller = new AbortController()
    pendingNavigation.current = controller
    const abort = () => controller.abort()
    options.signal.addEventListener('abort', abort, { once: true })
    beforeNavigate.current?.()
    const desiredTop =
      message.getBoundingClientRect().top -
      scroll.getBoundingClientRect().top +
      scroll.scrollTop -
      24
    const top = Math.max(0, Math.min(scroll.scrollHeight - scroll.clientHeight, desiredTop))
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const behavior =
      options.behavior === 'instant' ||
      options.source === 'scrub' ||
      reducedMotion ||
      Math.abs(top - scroll.scrollTop) > scroll.clientHeight
        ? 'instant'
        : 'smooth'

    const arrived = await new Promise<boolean>((resolve) => {
      let request: number | null = null
      const started = performance.now()
      const finish = (completed: boolean) => {
        if (request !== null) cancelAnimationFrame(request)
        controller.signal.removeEventListener('abort', cancel)
        scroll.removeEventListener('wheel', abort)
        scroll.removeEventListener('touchstart', abort)
        if (!completed) scroll.scrollTo({ top: scroll.scrollTop, behavior: 'instant' })
        resolve(completed)
      }
      const cancel = () => finish(false)
      const check = () => {
        if (controller.signal.aborted) return finish(false)
        if (Math.abs(scroll.scrollTop - top) <= 2) return finish(true)
        if (performance.now() - started > 1500) return finish(false)
        request = requestAnimationFrame(check)
      }
      controller.signal.addEventListener('abort', cancel, { once: true })
      scroll.addEventListener('wheel', abort, { once: true, passive: true })
      scroll.addEventListener('touchstart', abort, { once: true, passive: true })
      scroll.scrollTo({ top, behavior })
      request = requestAnimationFrame(check)
    })
    options.signal.removeEventListener('abort', abort)
    if (pendingNavigation.current !== controller) return
    pendingNavigation.current = null
    if (controller.signal.aborted || options.signal.aborted) return
    if (!arrived) throw new Error('The requested user message could not be reached.')
    setHighlightedId(id)
    highlightTimer.current = setTimeout(() => setHighlightedId(null), 1400)
    scheduleMeasurement.current()
  }, [])

  return {
    frameRef,
    scrollRef,
    contentRef,
    activeId,
    activeIds,
    availableSpace,
    railOffset: Math.max(0, (availableSpace - 36) / 2),
    highlightedId,
    registerMessage,
    waitForMessage,
    navigateTo,
    isNavigationPending,
    cancelNavigation,
  }
}
