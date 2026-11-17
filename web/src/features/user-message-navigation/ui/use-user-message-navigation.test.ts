// @vitest-environment jsdom

import { act, createElement, useLayoutEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import type { UserMessageNavigationOptions } from '../../../blocks/user-message-navigation-rail'
import { useUserMessageNavigation } from './use-user-message-navigation'

const ids = ['one', 'two', 'three', 'four']
const offsets = [0, 240, 700, 1000]
let container: HTMLDivElement
let root: Root
let navigation: ReturnType<typeof useUserMessageNavigation>
let scroll: HTMLDivElement
let content: HTMLDivElement
let scrollTo: Mock<(input?: ScrollToOptions | number, y?: number) => void>
let frameCallbacks: Map<number, FrameRequestCallback>
let resizeCallbacks: (() => void)[]
let mutationCallbacks: (() => void)[]
let contentLeft: number
let reducedMotion: boolean
let finishSmoothImmediately: boolean
let beforeNavigate: Mock<() => void>

function Harness() {
  const state = useUserMessageNavigation(ids, 'test-conversation', beforeNavigate)
  useLayoutEffect(() => {
    navigation = state
  })
  return createElement(
    'div',
    { ref: state.frameRef, 'data-frame': '' },
    createElement(
      'div',
      { ref: state.scrollRef, 'data-scroll': '' },
      createElement(
        'div',
        { ref: state.contentRef, 'data-content': '' },
        ids.map((id) =>
          createElement('article', {
            key: id,
            'data-message-id': id,
            ref: (element: HTMLElement | null) => state.registerMessage(id, element),
          }),
        ),
      ),
    ),
  )
}

function options(
  overrides: Partial<UserMessageNavigationOptions> = {},
): UserMessageNavigationOptions {
  return { source: 'click', behavior: 'smooth', signal: new AbortController().signal, ...overrides }
}

async function flushFrame() {
  await act(async () => {
    const callbacks = [...frameCallbacks.values()]
    frameCallbacks.clear()
    callbacks.forEach((callback) => callback(performance.now()))
  })
}

async function jump(id: string, navigationOptions = options()) {
  let completion: Promise<void> | undefined
  await act(async () => {
    completion = navigation.navigateTo(id, navigationOptions)
  })
  await flushFrame()
  await act(async () => completion)
}

beforeEach(async () => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  frameCallbacks = new Map()
  resizeCallbacks = []
  mutationCallbacks = []
  contentLeft = 90
  reducedMotion = false
  finishSmoothImmediately = true
  beforeNavigate = vi.fn<() => void>()
  let frameId = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameId += 1
    frameCallbacks.set(frameId, callback)
    return frameId
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frameCallbacks.delete(id))
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        resizeCallbacks.push(callback)
      }
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'MutationObserver',
    class {
      constructor(callback: () => void) {
        mutationCallbacks.push(callback)
      }
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: reducedMotion })),
  )
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => root.render(createElement(Harness)))
  const frame = container.querySelector<HTMLDivElement>('[data-frame]')!
  scroll = container.querySelector<HTMLDivElement>('[data-scroll]')!
  content = container.querySelector<HTMLDivElement>('[data-content]')!
  vi.spyOn(frame, 'getBoundingClientRect').mockImplementation(() => new DOMRect(10, 100, 1000, 400))
  vi.spyOn(scroll, 'getBoundingClientRect').mockImplementation(
    () => new DOMRect(10, 100, 1000, 400),
  )
  vi.spyOn(content, 'getBoundingClientRect').mockImplementation(
    () => new DOMRect(contentLeft, 100 - scroll.scrollTop, 760, 1600),
  )
  Object.defineProperties(scroll, {
    scrollHeight: { value: 1600, configurable: true },
    clientHeight: { value: 400, configurable: true },
  })
  scrollTo = vi.fn((input?: ScrollToOptions | number, y?: number) => {
    if (typeof input === 'number') {
      scroll.scrollTop = y ?? 0
    } else if (input?.behavior === 'instant' || finishSmoothImmediately) {
      scroll.scrollTop = input?.top ?? 0
    }
  })
  scroll.scrollTo = scrollTo
  ids.forEach((id, index) => {
    const element = content.querySelector<HTMLElement>(`[data-message-id="${id}"]`)!
    vi.spyOn(element, 'getBoundingClientRect').mockImplementation(
      () => new DOMRect(contentLeft, 100 + offsets[index] - scroll.scrollTop, 500, 40),
    )
  })
  await flushFrame()
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useUserMessageNavigation', () => {
  it('measures the actual left gutter and tracks all visible user messages', async () => {
    expect(navigation.availableSpace).toBe(80)
    expect(navigation.railOffset).toBe(22)
    expect(navigation.activeId).toBe('one')
    expect(navigation.activeIds).toEqual(['one', 'two'])

    contentLeft = 40
    await act(async () => resizeCallbacks.forEach((callback) => callback()))
    await flushFrame()
    expect(navigation.availableSpace).toBe(30)
    expect(navigation.railOffset).toBe(0)

    scroll.scrollTop = 220
    await act(async () => scroll.dispatchEvent(new Event('scroll')))
    await flushFrame()
    expect(navigation.activeId).toBe('two')
    expect(navigation.activeIds).toEqual(['two'])
  })

  it('rechecks mounted message geometry when transcript content changes', async () => {
    content.querySelector('[data-message-id="one"]')!.remove()
    await act(async () => mutationCallbacks.forEach((callback) => callback()))
    await flushFrame()

    expect(navigation.activeId).toBe('two')
    expect(navigation.activeIds).toEqual(['two'])
  })

  it('scrolls nearby destinations smoothly and highlights only after arriving for 1400ms', async () => {
    await jump('two')

    expect(scrollTo).toHaveBeenLastCalledWith({ top: 216, behavior: 'smooth' })
    expect(beforeNavigate).toHaveBeenCalledOnce()
    expect(navigation.highlightedId).toBe('two')
    await act(async () => vi.advanceTimersByTime(1399))
    expect(navigation.highlightedId).toBe('two')
    await act(async () => vi.advanceTimersByTime(1))
    expect(navigation.highlightedId).toBeNull()
  })

  it('jumps farther than one viewport instantly', async () => {
    await jump('four')

    expect(scrollTo).toHaveBeenLastCalledWith({ top: 976, behavior: 'instant' })
    expect(navigation.highlightedId).toBe('four')
  })

  it.each(['scrub', 'reduced-motion', 'explicit-instant'] as const)(
    'uses an instant jump for %s even when the target is nearby',
    async (mode) => {
      reducedMotion = mode === 'reduced-motion'
      await jump(
        'two',
        options({
          source: mode === 'scrub' ? 'scrub' : 'click',
          behavior: mode === 'explicit-instant' ? 'instant' : 'smooth',
        }),
      )

      expect(scrollTo).toHaveBeenLastCalledWith({ top: 216, behavior: 'instant' })
    },
  )

  it('cancels the previous smooth scroll when a newer jump takes ownership', async () => {
    finishSmoothImmediately = false
    let first: Promise<void> | undefined
    await act(async () => {
      first = navigation.navigateTo('two', options())
    })
    expect(navigation.highlightedId).toBeNull()

    await jump('four')
    await act(async () => first)

    expect(scrollTo.mock.calls.map(([value]) => value)).toEqual([
      { top: 216, behavior: 'smooth' },
      { top: 0, behavior: 'instant' },
      { top: 976, behavior: 'instant' },
    ])
    expect(navigation.highlightedId).toBe('four')
  })

  it('cancels a pending jump on the caller signal without highlighting it', async () => {
    finishSmoothImmediately = false
    const controller = new AbortController()
    let completion: Promise<void> | undefined
    await act(async () => {
      completion = navigation.navigateTo('two', options({ signal: controller.signal }))
    })
    await act(async () => controller.abort())
    await act(async () => completion)

    expect(scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: 'instant' })
    expect(navigation.highlightedId).toBeNull()
  })
})
