import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type {
  UserMessageNavigationItem,
  UserMessageNavigationOptions,
  UserMessageNavigationSource,
} from './model'

export type MessageNavigationCallbacks = {
  onNavigate: (id: string, options: UserMessageNavigationOptions) => void | Promise<void>
  onRevealItem?: (
    item: UserMessageNavigationItem,
    options: { signal: AbortSignal },
  ) => void | boolean | Promise<void | boolean>
}

export function useMessageNavigation(callbacks: MessageNavigationCallbacks) {
  const latest = useRef(callbacks)
  useLayoutEffect(() => {
    latest.current = callbacks
  })
  const controller = useRef<AbortController | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [errorId, setErrorId] = useState<string | null>(null)

  useEffect(() => () => controller.current?.abort(), [])

  const cancel = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    setBusyId(null)
  }, [])

  const navigate = useCallback(
    async (item: UserMessageNavigationItem, source: UserMessageNavigationSource) => {
      // Scrubbing must never fetch old history just because the pointer passes over it.
      if (source === 'scrub' && item.isLoaded === false) return false
      controller.current?.abort()
      const request = new AbortController()
      controller.current = request
      const { signal } = request
      const handlers = latest.current
      setErrorId(null)
      setBusyId(item.id)
      try {
        if (item.isLoaded === false) {
          if (!handlers.onRevealItem) throw new Error('History is not available')
          const revealed = await handlers.onRevealItem(item, { signal })
          if (signal.aborted) return false
          if (revealed === false) throw new Error('History could not be revealed')
        }
        if (signal.aborted) return false
        const reduced =
          typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
        await handlers.onNavigate(item.id, {
          signal,
          source,
          behavior: reduced || source === 'scrub' ? 'instant' : 'smooth',
        })
        return !signal.aborted
      } catch {
        if (!signal.aborted) setErrorId(item.id)
        return false
      } finally {
        if (controller.current === request && !signal.aborted) setBusyId(null)
      }
    },
    [],
  )

  return { navigate, cancel, busyId, errorId }
}
