import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import {
  PREVIEW_DELAY,
  type UserMessageNavigationItem,
  type UserMessagePreview,
  type UserMessagePreviewLoader,
  type UserMessagePreviewState,
} from './model'

export type UseMessagePreviewOptions = {
  item: UserMessageNavigationItem | null
  mode: 'hover' | 'focus' | null
  onPreviewItem?: UserMessagePreviewLoader
}

type PreviewResult = {
  preview: UserMessagePreview | undefined
  status: UserMessagePreviewState
}

type PendingPreview = {
  id: string
  controller: AbortController
  timer?: ReturnType<typeof setTimeout>
  started: boolean
  settled: boolean
  start: () => void
}

/** Owns lazy history previews; live message content remains owned by the source. */
export function useMessagePreview({
  item,
  mode,
  onPreviewItem,
}: UseMessagePreviewOptions): PreviewResult {
  const latest = useRef({ item, mode, onPreviewItem })
  const [cache, setCache] = useState(() => new Map<string, PreviewResult>())
  const pending = useRef<PendingPreview | null>(null)
  const itemId = item?.id ?? null
  // Read on every render: memoizing by item identity would freeze streamed text.
  const livePreview = item?.getPreview?.()
  const locallyLoaded = item !== null && item.isLoaded !== false
  const cached = itemId === null ? undefined : cache.get(itemId)
  const externallyFinished = item?.previewState === 'loaded' || item?.previewState === 'unavailable'
  const shouldRequest =
    item !== null &&
    !locallyLoaded &&
    livePreview === undefined &&
    cached === undefined &&
    !externallyFinished &&
    mode !== null &&
    onPreviewItem !== undefined

  useLayoutEffect(() => {
    latest.current = { item, mode, onPreviewItem }
  })

  useEffect(() => {
    if (!shouldRequest || itemId === null) return
    const request: PendingPreview = {
      id: itemId,
      controller: new AbortController(),
      started: false,
      settled: false,
      start,
    }
    pending.current = request

    function isCurrent() {
      return (
        pending.current === request &&
        !request.controller.signal.aborted &&
        latest.current.item?.id === request.id &&
        latest.current.mode !== null
      )
    }

    function start() {
      if (request.started || !isCurrent()) return
      clearTimeout(request.timer)
      request.started = true
      // Defer only to the microtask queue so StrictMode's cancelled setup cannot
      // invoke the loader. Keyboard focus still bypasses the hover delay.
      void Promise.resolve().then(async () => {
        if (!isCurrent()) return
        const selected = latest.current.item
        const load = latest.current.onPreviewItem
        if (!selected || !load) return
        let result: PreviewResult
        try {
          const preview = await load(selected, { signal: request.controller.signal })
          result =
            preview === null
              ? { preview: undefined, status: 'unavailable' }
              : { preview, status: 'loaded' }
        } catch {
          result = { preview: undefined, status: 'unavailable' }
        }
        if (!isCurrent()) return
        request.settled = true
        pending.current = null
        setCache((previous) => new Map(previous).set(request.id, result))
      })
    }

    if (latest.current.mode === 'focus') start()
    else request.timer = setTimeout(start, PREVIEW_DELAY)

    return () => {
      clearTimeout(request.timer)
      if (!request.settled) request.controller.abort()
      if (pending.current === request) pending.current = null
    }
  }, [itemId, shouldRequest])

  useEffect(() => {
    if (mode === 'focus' && pending.current?.id === itemId) pending.current.start()
  }, [itemId, mode, shouldRequest])

  if (livePreview !== undefined) return { preview: livePreview, status: 'loaded' }
  if (cached) return cached
  if (locallyLoaded) return { preview: undefined, status: item?.previewState ?? 'loaded' }
  return {
    preview: undefined,
    status: item?.previewState ?? (shouldRequest ? 'loading' : 'unavailable'),
  }
}
