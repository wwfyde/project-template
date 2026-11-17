// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  UserMessageNavigationRail,
  type UserMessageNavigationRailProps,
} from './user-message-navigation-rail'
import type { UserMessageNavigationItem, UserMessageNavigationOptions } from './model'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function makeItems(count: number): UserMessageNavigationItem[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `message-${index}`,
    turnKey: `turn-${index}`,
    bookmarkId: `bookmark-${index}`,
    getLabel: () => `User message ${index + 1}`,
    getPreview: () => ({ response: `Assistant response ${index + 1}` }),
  }))
}

async function render(props: UserMessageNavigationRailProps) {
  await act(async () => root.render(createElement(UserMessageNavigationRail, props)))
}

function marker(id: string): HTMLButtonElement {
  const element = container.querySelector<HTMLButtonElement>(
    `button[data-item-id="${id}"], button[data-thread-user-message-navigation-item-id="${id}"]`,
  )
  expect(element, `Expected user message ${id} to have a navigation marker`).not.toBeNull()
  return element!
}

function openPreview(role: 'tooltip' | 'dialog' = 'tooltip') {
  return document.querySelector<HTMLElement>(`[role="${role}"][data-open]`)
}

async function pressKey(key: string, options: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options })
  await act(async () => document.activeElement?.dispatchEvent(event))
  return event
}

function setKeyboardModality() {
  // jsdom does not derive :focus-visible from synthetic keyboard events.
  // oxlint-disable-next-line typescript/unbound-method -- Preserve the original receiver in the mock.
  const matches = Element.prototype.matches
  vi.spyOn(Element.prototype, 'matches').mockImplementation(function (this: Element, selector) {
    return selector === ':focus-visible'
      ? this === document.activeElement
      : matches.call(this, selector)
  })
}

async function focusMarker(id: string) {
  setKeyboardModality()
  await act(async () => marker(id).focus())
}

function railGeometry() {
  const list = container.querySelector<HTMLOListElement>('ol')!
  const markers = [...list.querySelectorAll<HTMLButtonElement>('button[data-item-id]')]
  markers.forEach((button, index) => {
    vi.spyOn(button, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, index * 10, 36, 10))
  })
  vi.spyOn(list, 'getBoundingClientRect').mockReturnValue(
    new DOMRect(0, 0, 36, markers.length * 10),
  )
  let captured = false
  const capture = vi.fn(() => {
    captured = true
  })
  const release = vi.fn(() => {
    captured = false
  })
  Object.assign(list, {
    setPointerCapture: capture,
    hasPointerCapture: () => captured,
    releasePointerCapture: release,
  })
  return { list, capture, release }
}

async function pointerEvent(
  list: HTMLElement,
  type: string,
  index: number,
  buttons = 1,
  pointerType = 'mouse',
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: 18,
    clientY: index * 10 + 5,
    button: 0,
    buttons,
  })
  Object.defineProperties(event, {
    pointerId: { value: 1 },
    pointerType: { value: pointerType },
    isPrimary: { value: true },
  })
  await act(async () => list.dispatchEvent(event))
}

describe('UserMessageNavigationRail', () => {
  it('only appears for at least four user messages with enough layout space', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(3), activeId: 'message-0', onNavigate })
    expect(container.querySelector('nav')).toBeNull()

    await render({ items: makeItems(4), activeId: 'message-0', availableSpace: 47, onNavigate })
    expect(container.querySelector('nav')).toBeNull()

    await render({ items: makeItems(4), activeId: 'message-0', availableSpace: 48, onNavigate })
    expect(container.querySelector('nav')).not.toBeNull()
    expect(marker('message-0')).not.toBeNull()
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it.each(['space', 'count'] as const)(
    'discards previews and aborts pending navigation when hidden by %s',
    async (reason) => {
      const items = makeItems(6)
      let completeNavigation: (() => void) | undefined
      const onNavigate = vi.fn(
        (_id: string, _options: UserMessageNavigationOptions) =>
          new Promise<void>((resolve) => {
            completeNavigation = resolve
          }),
      )
      const props = {
        items,
        activeId: 'message-0',
        onNavigate,
        shortcutScopeRef: { current: container },
      }
      await render(props)
      await focusMarker('message-1')
      const previousMarker = marker('message-1')
      expect(openPreview()).not.toBeNull()
      await act(async () => previousMarker.click())
      const signal = onNavigate.mock.calls[0][1].signal
      expect(signal.aborted).toBe(false)

      await render(
        reason === 'space'
          ? { ...props, availableSpace: 47 }
          : { ...props, items: items.slice(0, 3) },
      )

      expect(container.querySelector('nav')).toBeNull()
      expect(openPreview()).toBeNull()
      expect(signal.aborted).toBe(true)
      await act(async () =>
        container.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'ArrowDown', altKey: true, bubbles: true }),
        ),
      )
      expect(onNavigate).toHaveBeenCalledTimes(1)
      await render(props)
      expect(marker('message-1')).not.toBe(previousMarker)
      expect(openPreview()).toBeNull()
      expect(marker('message-0').tabIndex).toBe(0)
      await act(async () => completeNavigation!())
      expect(openPreview()).toBeNull()
      expect(marker('message-0').hasAttribute('aria-current')).toBe(true)
    },
  )

  it('does not restore an old scrub session after the rail is hidden and shown again', async () => {
    const items = makeItems(6)
    let completeNavigation: (() => void) | undefined
    const onNavigate = vi.fn(
      (_id: string, _options: UserMessageNavigationOptions) =>
        new Promise<void>((resolve) => {
          completeNavigation = resolve
        }),
    )
    await render({ items, activeId: 'message-0', onNavigate })
    const oldGeometry = railGeometry()
    await pointerEvent(oldGeometry.list, 'pointerdown', 0)
    await pointerEvent(oldGeometry.list, 'pointermove', 1)
    expect(oldGeometry.capture).toHaveBeenCalledWith(1)
    const signal = onNavigate.mock.calls[0][1].signal

    await render({ items, activeId: 'message-0', onNavigate, availableSpace: 20 })
    expect(oldGeometry.list.isConnected).toBe(false)
    expect(signal.aborted).toBe(true)
    await render({ items, activeId: 'message-0', onNavigate })
    const { list } = railGeometry()
    expect(list).not.toBe(oldGeometry.list)
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
    await pointerEvent(list, 'pointermove', 3)
    expect(onNavigate).toHaveBeenCalledTimes(1)
    await act(async () => completeNavigation!())
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
  })

  it('clears removed selection and cancels its reveal without reopening it on reinsertion', async () => {
    const items = makeItems(6)
    items[1] = { ...items[1], isLoaded: false }
    let reveal: (() => void) | undefined
    const onRevealItem = vi.fn(
      (_item: UserMessageNavigationItem, _options: { signal: AbortSignal }) =>
        new Promise<void>((resolve) => {
          reveal = resolve
        }),
    )
    const onNavigate = vi.fn()
    const props = { items, activeId: 'message-0', onNavigate, onRevealItem }
    await render(props)
    await focusMarker('message-1')
    expect(openPreview()).not.toBeNull()
    await act(async () => marker('message-1').click())
    const signal = onRevealItem.mock.calls[0][1].signal

    await render({ ...props, items: items.filter((item) => item.id !== 'message-1') })

    expect(container.querySelector('nav')).not.toBeNull()
    expect(openPreview()).toBeNull()
    expect(signal.aborted).toBe(true)
    expect(marker('message-0').tabIndex).toBe(0)
    await render(props)
    expect(openPreview()).toBeNull()
    await act(async () => reveal!())
    expect(onNavigate).not.toHaveBeenCalled()
    expect(openPreview()).toBeNull()
  })

  it('indexes the entire message history instead of truncating it to twenty items', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(128), activeId: 'message-0', onNavigate })

    expect(marker('message-0')).not.toBeNull()
    expect(marker('message-127')).not.toBeNull()
    expect(
      container.querySelectorAll(
        'button[data-item-id], button[data-thread-user-message-navigation-item-id]',
      ),
    ).toHaveLength(128)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('keeps keyboard preview selection independent from all visible reading markers', async () => {
    const onNavigate = vi.fn()
    await render({
      items: makeItems(8),
      activeId: 'message-0',
      activeIds: ['message-0', 'message-1'],
      onNavigate,
    })
    await focusMarker('message-2')

    expect(openPreview()?.textContent).toContain('User message 3')
    expect(openPreview()?.textContent).toContain('Assistant response 3')
    expect(container.querySelectorAll('[aria-current]')).toHaveLength(2)
    expect(marker('message-0').hasAttribute('aria-current')).toBe(true)
    expect(marker('message-1').hasAttribute('aria-current')).toBe(true)
    expect(marker('message-2').hasAttribute('aria-current')).toBe(false)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('shows two output labels and a remaining count without interpreting HTML', async () => {
    const items = makeItems(4)
    items[1] = {
      ...items[1],
      getLabel: () => '<img src=x onerror=alert(1)>',
      getPreview: () => ({
        response: '<script>unsafe()</script>',
        outputs: [
          { id: 'one', label: 'Brief.md', type: 'file' },
          { id: 'two', label: 'Website preview', type: 'website' },
          { id: 'three', label: 'Private third label', type: 'review' },
        ],
      }),
    }
    await render({ items, activeId: 'message-0', onNavigate: vi.fn() })
    await focusMarker('message-1')

    const preview = openPreview()!
    expect(preview.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(preview.textContent).toContain('<script>unsafe()</script>')
    expect(preview.textContent).toContain('Brief.md')
    expect(preview.textContent).toContain('Website preview')
    expect(preview.textContent).toContain('+1')
    expect(preview.textContent).not.toContain('Private third label')
    expect(preview.querySelector('script, img')).toBeNull()
  })

  it('preserves message DOM identity when older messages are prepended and response text streams', async () => {
    const items = makeItems(4)
    const onNavigate = vi.fn()
    await render({ items, activeId: 'message-2', onNavigate })
    await focusMarker('message-2')
    const selected = marker('message-2')
    const history = makeItems(25).map((item) => ({ ...item, id: `history-${item.id}` }))

    await render({
      items: [
        ...history,
        ...items.map((item) =>
          item.id === 'message-2'
            ? { ...item, getPreview: () => ({ response: 'New streamed content' }) }
            : item,
        ),
      ],
      activeId: 'message-2',
      onNavigate,
    })

    expect(marker('message-2')).toBe(selected)
    expect(document.activeElement).toBe(selected)
    expect(openPreview()?.textContent).toContain('New streamed content')
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('supports keyboard selection to the ends without navigating until activation', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(80), activeId: 'message-0', onNavigate })
    await focusMarker('message-0')
    await pressKey('End')
    expect(document.activeElement).toBe(marker('message-79'))
    await pressKey('ArrowUp')
    expect(document.activeElement).toBe(marker('message-78'))
    await pressKey('Home')
    expect(document.activeElement).toBe(marker('message-0'))
    expect(onNavigate).not.toHaveBeenCalled()

    // Native Enter/Space-to-click synthesis is checked in the browser; jsdom does not synthesize it.
    expect((await pressKey('Enter')).defaultPrevented).toBe(false)
    await act(async () => marker('message-0').click())
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-0')
  })

  it('opens an interactive preview only when a bookmark action is available', async () => {
    const items = makeItems(4)
    const onBookmarkChange = vi.fn()
    await render({ items, activeId: 'message-0', onNavigate: vi.fn(), onBookmarkChange })
    await focusMarker('message-1')

    expect(openPreview('tooltip')).toBeNull()
    const dialog = openPreview('dialog')!
    expect(dialog).not.toBeNull()
    await pressKey('ArrowRight')
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    })
    const bookmark = dialog.querySelector<HTMLButtonElement>('button')!
    expect(document.activeElement).toBe(bookmark)
    await act(async () => bookmark.click())
    expect(onBookmarkChange).toHaveBeenCalledExactlyOnceWith(items[1], true)
    await pressKey('Escape')
    expect(document.activeElement).toBe(marker('message-1'))
    expect(openPreview('dialog')).toBeNull()
  })

  it('reveals an unloaded target before requesting its navigation', async () => {
    const items = makeItems(4)
    items[1] = { ...items[1], isLoaded: false }
    let reveal: (() => void) | undefined
    const order: string[] = []
    const onRevealItem = vi.fn(() => {
      order.push('reveal')
      return new Promise<void>((resolve) => {
        reveal = resolve
      })
    })
    const onNavigate = vi.fn((_id: string) => {
      order.push('navigate')
    })
    await render({ items, activeId: 'message-0', onNavigate, onRevealItem })
    await act(async () => marker('message-1').click())
    expect(onRevealItem).toHaveBeenCalledTimes(1)
    expect(onNavigate).not.toHaveBeenCalled()
    await act(async () => reveal!())
    expect(order).toEqual(['reveal', 'navigate'])
    expect(onNavigate.mock.calls[0][0]).toBe('message-1')
  })

  it('aborts a stale history reveal so a slower old target cannot override the latest click', async () => {
    const items = makeItems(4)
    items[0] = { ...items[0], isLoaded: false }
    let reveal: (() => void) | undefined
    const onRevealItem = vi.fn(
      (_item: UserMessageNavigationItem, _options: { signal: AbortSignal }) => {
        return new Promise<void>((resolve) => {
          reveal = resolve
        })
      },
    )
    const onNavigate = vi.fn()
    await render({ items, activeId: 'message-2', onNavigate, onRevealItem })
    await act(async () => marker('message-0').click())
    await act(async () => marker('message-3').click())
    expect(onRevealItem.mock.calls[0][1].signal.aborted).toBe(true)
    await act(async () => reveal!())

    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-3')
  })
  it('reports unavailable history without pretending that navigation succeeded', async () => {
    const items = makeItems(4)
    items[1] = { ...items[1], isLoaded: false }
    const onNavigate = vi.fn()
    const onRevealItem = vi.fn(async () => false)
    await render({
      items,
      activeId: 'message-0',
      onNavigate,
      onRevealItem,
      labels: { navigationError: 'This history is unavailable.' },
    })
    await act(async () => marker('message-1').click())

    expect(onNavigate).not.toHaveBeenCalled()
    expect(container.textContent).toContain('This history is unavailable.')
    expect(marker('message-1').hasAttribute('aria-busy')).toBe(false)
  })

  it('scrubs only loaded messages and suppresses the release click without a duplicate jump', async () => {
    const items = makeItems(6)
    items[2] = { ...items[2], isLoaded: false }
    const onNavigate = vi.fn()
    const onRevealItem = vi.fn()
    await render({ items, activeId: 'message-0', onNavigate, onRevealItem })
    const { list, capture, release } = railGeometry()

    await pointerEvent(list, 'pointerdown', 0)
    expect(onNavigate).not.toHaveBeenCalled()
    await pointerEvent(list, 'pointermove', 1)
    expect(capture).toHaveBeenCalledWith(1)
    expect(list.hasAttribute('data-scrubbing')).toBe(true)
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-1')
    expect(onNavigate.mock.calls[0][1]).toMatchObject({ source: 'scrub', behavior: 'instant' })

    await pointerEvent(list, 'pointermove', 2)
    expect(onRevealItem).not.toHaveBeenCalled()
    expect(onNavigate).toHaveBeenCalledTimes(1)
    await pointerEvent(list, 'pointermove', 3)
    expect(onNavigate).toHaveBeenCalledTimes(2)
    expect(onNavigate.mock.calls[1][0]).toBe('message-3')
    await pointerEvent(list, 'pointerup', 3, 0)
    expect(release).toHaveBeenCalledWith(1)
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
    await act(async () =>
      marker('message-3').dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })),
    )
    expect(onNavigate).toHaveBeenCalledTimes(2)
  })

  it('releases a cancelled drag and allows the next independent click', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(5), activeId: 'message-0', onNavigate })
    const { list, release } = railGeometry()
    await pointerEvent(list, 'pointerdown', 0)
    await pointerEvent(list, 'pointermove', 1)
    await pointerEvent(list, 'pointercancel', 1, 0)
    expect(release).toHaveBeenCalledWith(1)
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
    expect(openPreview()).toBeNull()
    await pointerEvent(list, 'pointerdown', 3)
    await pointerEvent(list, 'pointerup', 3, 0)
    await act(async () =>
      marker('message-3').dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })),
    )
    expect(onNavigate).toHaveBeenCalledTimes(2)
    expect(onNavigate.mock.calls[1][0]).toBe('message-3')
    expect(onNavigate.mock.calls[1][1].source).toBe('click')
  })

  it.each(['pointercancel', 'lostpointercapture'])(
    'aborts pending scrub navigation on %s',
    async (eventType) => {
      let completeNavigation: (() => void) | undefined
      const onNavigate = vi.fn(
        (_id: string, _options: UserMessageNavigationOptions) =>
          new Promise<void>((resolve) => {
            completeNavigation = resolve
          }),
      )
      await render({ items: makeItems(6), activeId: 'message-0', onNavigate })
      const { list } = railGeometry()
      await pointerEvent(list, 'pointerdown', 0)
      await pointerEvent(list, 'pointermove', 2)
      const signal = onNavigate.mock.calls[0][1].signal
      expect(signal.aborted).toBe(false)
      expect(marker('message-2').getAttribute('aria-busy')).toBe('true')

      await pointerEvent(list, eventType, 2, 0)

      expect(signal.aborted).toBe(true)
      expect(list.hasAttribute('data-scrubbing')).toBe(false)
      expect(marker('message-2').hasAttribute('aria-busy')).toBe(false)
      expect(openPreview()).toBeNull()
      await act(async () => completeNavigation!())
      expect(onNavigate).toHaveBeenCalledTimes(1)
      expect(openPreview()).toBeNull()
    },
  )

  it('keeps the final asynchronous scrub navigation alive after normal pointer release', async () => {
    let completeNavigation: (() => void) | undefined
    const onNavigate = vi.fn(
      (_id: string, _options: UserMessageNavigationOptions) =>
        new Promise<void>((resolve) => {
          completeNavigation = resolve
        }),
    )
    await render({ items: makeItems(6), activeId: 'message-0', onNavigate })
    const { list } = railGeometry()
    await pointerEvent(list, 'pointerdown', 0)
    await pointerEvent(list, 'pointermove', 2)
    const signal = onNavigate.mock.calls[0][1].signal

    await pointerEvent(list, 'pointerup', 2, 0)
    // Native capture release may subsequently emit lostpointercapture.
    await pointerEvent(list, 'lostpointercapture', 2, 0)

    expect(signal.aborted).toBe(false)
    expect(marker('message-2').getAttribute('aria-busy')).toBe('true')
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
    await act(async () => completeNavigation!())
    expect(marker('message-2').hasAttribute('aria-busy')).toBe(false)
    expect(signal.aborted).toBe(false)
  })

  it('clamps captured dragging to the visible list boundary', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(8), activeId: 'message-0', onNavigate })
    const { list } = railGeometry()
    vi.spyOn(list, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 36, 20))
    await pointerEvent(list, 'pointerdown', 0)
    await pointerEvent(list, 'pointermove', 7)

    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-1')
  })

  it('ends dragging if a move arrives after the primary button was released', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(6), activeId: 'message-0', onNavigate })
    const { list, release } = railGeometry()
    await pointerEvent(list, 'pointerdown', 0)
    await pointerEvent(list, 'pointermove', 1)
    await pointerEvent(list, 'pointermove', 4, 0)

    expect(release).toHaveBeenCalledWith(1)
    expect(list.hasAttribute('data-scrubbing')).toBe(false)
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(openPreview()).toBeNull()
  })

  it('keeps touch movement available for native list scrolling and allows tap navigation', async () => {
    const onNavigate = vi.fn()
    await render({ items: makeItems(6), activeId: 'message-0', onNavigate })
    const { list, capture } = railGeometry()
    await pointerEvent(list, 'pointerdown', 1, 1, 'touch')
    await pointerEvent(list, 'pointermove', 3, 1, 'touch')
    await pointerEvent(list, 'pointerup', 3, 0, 'touch')

    expect(capture).not.toHaveBeenCalled()
    expect(onNavigate).not.toHaveBeenCalled()
    await act(async () =>
      marker('message-3').dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })),
    )
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-3')
  })

  it('scopes Alt-arrow shortcuts and allows them from focused rail markers', async () => {
    const onNavigate = vi.fn()
    await render({
      items: makeItems(6),
      activeId: 'message-1',
      onNavigate,
      shortcutScopeRef: { current: container },
    })
    const input = document.createElement('textarea')
    container.append(input)
    input.focus()
    await pressKey('ArrowDown', { altKey: true })
    expect(onNavigate).not.toHaveBeenCalled()
    const outside = document.createElement('button')
    document.body.append(outside)
    outside.focus()
    await pressKey('ArrowDown', { altKey: true })
    expect(onNavigate).not.toHaveBeenCalled()
    outside.remove()
    input.remove()

    await focusMarker('message-1')
    await pressKey('ArrowDown', { altKey: true })
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onNavigate.mock.calls[0][0]).toBe('message-2')
    expect(onNavigate.mock.calls[0][1].source).toBe('shortcut')
  })
})
