// @vitest-environment jsdom

import { act, createElement, StrictMode, useLayoutEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  UserMessageNavigationItem,
  UserMessagePreview,
  UserMessagePreviewLoader,
} from './model'
import { useMessagePreview, type UseMessagePreviewOptions } from './use-message-preview'

let root: Root
let container: HTMLDivElement
let mounted: boolean
let result: ReturnType<typeof useMessagePreview>

function Probe(props: UseMessagePreviewOptions) {
  const value = useMessagePreview(props)
  useLayoutEffect(() => {
    result = value
  })
  return null
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  mounted = true
})

afterEach(async () => {
  if (mounted) await act(async () => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function render(props: UseMessagePreviewOptions, strict = false) {
  await act(async () =>
    root.render(
      strict
        ? createElement(StrictMode, null, createElement(Probe, props))
        : createElement(Probe, props),
    ),
  )
}

async function advance(milliseconds: number) {
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds))
}

function historyItem(id: string): UserMessageNavigationItem {
  return { id, getLabel: () => id, isLoaded: false }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('useMessagePreview', () => {
  it('reads live getters on every render and never requests an already loaded message', async () => {
    let text = 'First streamed words'
    const item: UserMessageNavigationItem = {
      id: 'live',
      getLabel: () => 'Current question',
      getPreview: () => ({ response: text }),
    }
    const load = vi.fn<UserMessagePreviewLoader>()
    await render({ item, mode: 'hover', onPreviewItem: load })
    expect(result).toEqual({ preview: { response: text }, status: 'loaded' })

    text = 'First streamed words and the next sentence'
    await render({ item, mode: 'hover', onPreviewItem: load })
    await advance(500)

    expect(result.preview?.response).toBe(text)
    expect(load).not.toHaveBeenCalled()
  })

  it('waits 150ms on hover without restarting when parent callbacks or item objects change', async () => {
    const pending = deferred<UserMessagePreview | null>()
    const original = vi.fn<UserMessagePreviewLoader>()
    const latest = vi.fn<UserMessagePreviewLoader>(() => pending.promise)
    await render({ item: historyItem('a'), mode: 'hover', onPreviewItem: original })
    expect(result.status).toBe('loading')
    await advance(100)
    await render({ item: historyItem('a'), mode: 'hover', onPreviewItem: latest })
    await advance(49)
    expect(latest).not.toHaveBeenCalled()

    await advance(1)

    expect(original).not.toHaveBeenCalled()
    expect(latest).toHaveBeenCalledOnce()
    expect(latest.mock.calls[0][0].id).toBe('a')
    await act(async () => pending.resolve({ response: 'Loaded history' }))
    expect(result).toEqual({ preview: { response: 'Loaded history' }, status: 'loaded' })
  })

  it('loads immediately on focus and reuses the in-flight request when the input mode changes', async () => {
    const pending = deferred<UserMessagePreview | null>()
    const load = vi.fn<UserMessagePreviewLoader>(() => pending.promise)
    const item = historyItem('a')
    await render({ item, mode: 'hover', onPreviewItem: load })
    await advance(50)

    await render({ item, mode: 'focus', onPreviewItem: load })

    expect(load).toHaveBeenCalledOnce()
    const signal = load.mock.calls[0][1].signal
    await render({ item, mode: 'hover', onPreviewItem: load })
    await render({ item, mode: 'focus', onPreviewItem: load })
    await advance(500)
    expect(load).toHaveBeenCalledOnce()
    expect(signal.aborted).toBe(false)
    await act(async () => pending.resolve({ response: 'One request' }))
    expect(result.preview?.response).toBe('One request')
  })

  it('cancels rapid hover timers and discards stale responses even if the loader ignores abort', async () => {
    const requests = new Map<string, ReturnType<typeof deferred<UserMessagePreview | null>>>()
    const load = vi.fn<UserMessagePreviewLoader>((item) => {
      const request = deferred<UserMessagePreview | null>()
      requests.set(item.id, request)
      return request.promise
    })
    await render({ item: historyItem('skipped'), mode: 'hover', onPreviewItem: load })
    await advance(100)
    await render({ item: historyItem('a'), mode: 'hover', onPreviewItem: load })
    await advance(150)
    expect(load.mock.calls.map(([item]) => item.id)).toEqual(['a'])
    const firstSignal = load.mock.calls[0][1].signal

    await render({ item: historyItem('b'), mode: 'focus', onPreviewItem: load })

    expect(firstSignal.aborted).toBe(true)
    await act(async () => requests.get('b')!.resolve({ response: 'Newest selection' }))
    await act(async () => requests.get('a')!.resolve({ response: 'Stale response' }))
    expect(result.preview?.response).toBe('Newest selection')
    // An aborted response must not populate a cache entry either.
    await render({ item: historyItem('a'), mode: 'focus', onPreviewItem: load })
    expect(load.mock.calls.map(([item]) => item.id)).toEqual(['a', 'b', 'a'])
  })

  it('caches successful previews by ID ahead of an external loading state', async () => {
    const item = { ...historyItem('a'), previewState: 'loading' as const }
    const load = vi.fn<UserMessagePreviewLoader>(async () => ({ response: 'Cached response' }))
    await render({ item, mode: 'focus', onPreviewItem: load })
    expect(result.status).toBe('loaded')
    await render({ item: null, mode: null, onPreviewItem: load })

    await render({ item: { ...item }, mode: 'hover', onPreviewItem: load })
    await advance(300)

    expect(result).toEqual({ preview: { response: 'Cached response' }, status: 'loaded' })
    expect(load).toHaveBeenCalledOnce()
  })

  it.each(['null', 'reject'] as const)(
    'keeps an unavailable result stable after a %s response',
    async (outcome) => {
      const item = { ...historyItem('a'), previewState: 'loading' as const }
      const load = vi.fn<UserMessagePreviewLoader>(async () => {
        if (outcome === 'reject') throw new Error('History is unavailable')
        return null
      })
      await render({ item, mode: 'focus', onPreviewItem: load })
      expect(result).toEqual({ preview: undefined, status: 'unavailable' })
      await render({ item: null, mode: null, onPreviewItem: load })
      await render({ item, mode: 'focus', onPreviewItem: load })
      expect(result.status).toBe('unavailable')
      expect(load).toHaveBeenCalledOnce()
    },
  )

  it('prefers newly loaded live content and aborts an obsolete history request', async () => {
    const pending = deferred<UserMessagePreview | null>()
    const load = vi.fn<UserMessagePreviewLoader>(() => pending.promise)
    await render({ item: historyItem('a'), mode: 'focus', onPreviewItem: load })
    const signal = load.mock.calls[0][1].signal
    const live = {
      ...historyItem('a'),
      isLoaded: true,
      getPreview: () => ({ response: 'Live response' }),
    }

    await render({ item: live, mode: 'focus', onPreviewItem: load })

    expect(signal.aborted).toBe(true)
    await act(async () => pending.resolve({ response: 'Old history' }))
    expect(result).toEqual({ preview: { response: 'Live response' }, status: 'loaded' })
  })

  it('cancels waiting work on dismissal and aborts pending work on unmount', async () => {
    const pending = deferred<UserMessagePreview | null>()
    const load = vi.fn<UserMessagePreviewLoader>(() => pending.promise)
    const item = historyItem('a')
    await render({ item, mode: 'hover', onPreviewItem: load })
    await advance(100)
    await render({ item, mode: null, onPreviewItem: load })
    await advance(300)
    expect(load).not.toHaveBeenCalled()

    await render({ item, mode: 'focus', onPreviewItem: load })
    const signal = load.mock.calls[0][1].signal
    await act(async () => root.unmount())
    mounted = false

    expect(signal.aborted).toBe(true)
    await act(async () => pending.resolve({ response: 'Arrived after unmount' }))
  })

  it('does not duplicate a focus request during StrictMode effect replay', async () => {
    const load = vi.fn<UserMessagePreviewLoader>(async () => ({ response: 'One focus request' }))
    await render({ item: historyItem('a'), mode: 'focus', onPreviewItem: load }, true)

    expect(load).toHaveBeenCalledOnce()
    expect(result.preview?.response).toBe('One focus request')
  })
})
