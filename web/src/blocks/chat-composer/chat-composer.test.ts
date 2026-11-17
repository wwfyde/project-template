// @vitest-environment jsdom

import { act, createElement, useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatComposer } from './chat-composer'
import type { ChatComposerProps } from './types'
import { SegmentedTabs } from '../../components/ui/segmented-tabs'

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

function props(overrides: Partial<ChatComposerProps> = {}): ChatComposerProps {
  return {
    value: 'Hello',
    onValueChange: vi.fn(),
    attachments: [],
    onFilesAdded: vi.fn(),
    onRemoveAttachment: vi.fn(),
    modelId: 'auto',
    models: [
      { id: 'auto', label: 'Auto' },
      { id: 'fast', label: 'Fast' },
    ],
    onModelChange: vi.fn(),
    tools: [{ id: 'web', label: 'Web search', enabled: false }],
    onToolToggle: vi.fn(),
    busy: false,
    onSubmit: vi.fn(),
    onStop: vi.fn(),
    labels: {
      input: 'Message',
      placeholder: 'Ask anything',
      addFiles: 'Add files',
      removeAttachment: 'Remove attachment',
      model: 'Choose model',
      tools: 'Tools',
      submit: 'Send',
      stop: 'Stop',
      dropFiles: 'Drop files here',
      keyboardHint: 'Enter to send; Shift+Enter for a new line.',
      attachmentHint: 'Local preview only.',
      addContext: 'Add context',
      removeSelection: 'Remove selection',
      uploadDescription: 'From your computer',
    },
    ...overrides,
  }
}

async function render(value: ChatComposerProps) {
  await act(async () => root.render(createElement(ChatComposer, value)))
}

function button(label: string) {
  const element = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  expect(element).not.toBeNull()
  return element!
}

async function pressEnter(init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })
  await act(async () => container.querySelector('textarea')!.dispatchEvent(event))
  return event
}

describe('ChatComposer', () => {
  it('submits on Enter but leaves Shift+Enter and IME composition alone', async () => {
    const value = props()
    await render(value)

    expect((await pressEnter({ shiftKey: true })).defaultPrevented).toBe(false)
    expect((await pressEnter({ isComposing: true })).defaultPrevented).toBe(false)
    expect((await pressEnter({ keyCode: 229 })).defaultPrevented).toBe(false)
    await act(async () =>
      container.querySelector('textarea')!.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })),
    )
    expect((await pressEnter()).defaultPrevented).toBe(false)
    expect(value.onSubmit).not.toHaveBeenCalled()

    await act(async () =>
      container.querySelector('textarea')!.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true })),
    )
    expect((await pressEnter()).defaultPrevented).toBe(true)
    expect(value.onSubmit).toHaveBeenCalledExactlyOnceWith()
    await pressEnter({ repeat: true })
    expect(value.onSubmit).toHaveBeenCalledTimes(1)
  })

  it('rejects whitespace via both keyboard and form while allowing an attachment-only message', async () => {
    const value = props({ value: ' \n  ' })
    await render(value)
    expect(button('Send').disabled).toBe(true)
    await pressEnter()
    await act(async () =>
      container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
    )
    expect(value.onSubmit).not.toHaveBeenCalled()

    await render({ ...value, attachments: [{ id: 'f1', name: 'notes.txt', size: 400 }] })
    expect(button('Send').disabled).toBe(false)
    await act(async () => button('Send').click())
    expect(value.onSubmit).toHaveBeenCalledExactlyOnceWith()
  })

  it('swaps send for stop while busy, blocks file mutation, and preserves the editable draft', async () => {
    const value = props({ busy: true, attachments: [{ id: 'f1', name: 'notes.txt', size: 400 }] })
    await render(value)
    expect(container.querySelector('button[aria-label="Send"]')).toBeNull()
    expect(container.querySelector('textarea')!.disabled).toBe(false)
    expect(container.querySelector('textarea')!.value).toBe('Hello')
    expect(button('Add context').disabled).toBe(true)
    expect(button('Remove attachment: notes.txt').disabled).toBe(true)
    expect(button('Choose model').disabled).toBe(true)
    await pressEnter()
    expect(value.onSubmit).not.toHaveBeenCalled()
    await act(async () => button('Stop').click())
    expect(value.onStop).toHaveBeenCalledExactlyOnceWith()
  })

  it('stops synchronously without submitting the next draft through the click default action', async () => {
    const onSubmit = vi.fn()
    const onStop = vi.fn()
    const value = props({ value: 'next draft', onSubmit })

    function StatefulComposer() {
      const [busy, setBusy] = useState(true)
      return createElement(ChatComposer, {
        ...value,
        busy,
        onStop: () => {
          onStop()
          // Commit before the native click default action, matching a synchronous
          // run cancellation that replaces the stop control with a submit button.
          flushSync(() => setBusy(false))
        },
      })
    }

    await act(async () => root.render(createElement(StatefulComposer)))
    await act(async () => button('Stop').click())

    expect(onStop).toHaveBeenCalledExactlyOnceWith()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(container.querySelector('textarea')!.value).toBe('next draft')
    expect(container.querySelector('button[aria-label="Stop"]')).toBeNull()
    expect(button('Send').disabled).toBe(false)

    await act(async () => button('Send').click())
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith()
  })

  it('reports selected, dropped, and pasted files without uploading them', async () => {
    const value = props()
    const file = new File(['notes'], 'notes.txt', { type: 'text/plain' })
    await render(value)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(input, 'files', { value: [file] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(value.onFilesAdded).toHaveBeenLastCalledWith([file])

    const drop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [file], types: ['Files'] } })
    await act(async () => container.querySelector('form')!.dispatchEvent(drop))
    expect(drop.defaultPrevented).toBe(true)
    expect(value.onFilesAdded).toHaveBeenCalledTimes(2)

    const paste = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(paste, 'clipboardData', { value: { files: [file] } })
    await act(async () => container.querySelector('textarea')!.dispatchEvent(paste))
    expect(paste.defaultPrevented).toBe(true)
    expect(value.onFilesAdded).toHaveBeenCalledTimes(3)

    await render({ ...value, busy: true })
    await act(async () => container.querySelector('form')!.dispatchEvent(drop))
    expect(value.onFilesAdded).toHaveBeenCalledTimes(3)
  })

  it('removes an attachment by stable id and associates validation errors with the input', async () => {
    const value = props({
      attachments: [{ id: 'file-12', name: 'notes.txt', size: 400 }],
      error: 'The file is too large.',
    })
    await render(value)
    await act(async () => button('Remove attachment: notes.txt').click())
    expect(value.onRemoveAttachment).toHaveBeenCalledExactlyOnceWith('file-12')
    const error = container.querySelector('[role="alert"]')!
    expect(container.querySelector('textarea')!.getAttribute('aria-describedby')).toContain(error.id)
    expect(container.querySelector('textarea')!.getAttribute('aria-invalid')).toBe('true')
  })

  it('selects a model through an accessible menu and toggles a tool without changing the model', async () => {
    const value = props()
    await render(value)
    await act(async () => button('Choose model').click())
    const model = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitemradio"]')).find(
      (item) => item.textContent === 'Fast',
    )
    expect(model).toBeDefined()
    await act(async () => model!.click())
    expect(value.onModelChange).toHaveBeenCalledExactlyOnceWith('fast')

    await act(async () => button('Add context').click())
    const tool = document.querySelector<HTMLElement>('[role="menuitemcheckbox"]')!
    expect(tool?.getAttribute('aria-checked')).toBe('false')
    await act(async () => tool.click())
    expect(value.onToolToggle).toHaveBeenCalledExactlyOnceWith('web')
    expect(value.onModelChange).toHaveBeenCalledTimes(1)
  })

  it('opens the plus menu first and opens the file picker only after choosing upload', async () => {
    const value = props()
    await render(value)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    const chooseFiles = vi.spyOn(input, 'click').mockImplementation(() => {})
    await act(async () => button('Add context').click())
    expect(button('Add context').getAttribute('aria-expanded')).toBe('true')
    expect(chooseFiles).not.toHaveBeenCalled()
    const upload = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) =>
      item.textContent?.includes('Add files'),
    )!
    expect(upload.textContent).toContain('From your computer')
    await act(async () => upload.click())
    expect(chooseFiles).toHaveBeenCalledExactlyOnceWith()
    expect(button('Add context').getAttribute('aria-expanded')).toBe('false')
    expect(container.querySelector('input[type="file"]')).toBe(input)
    expect(value.onSubmit).not.toHaveBeenCalled()
  })

  it('dispatches host actions, exposes unavailable reasons, and freezes an already-open menu while busy', async () => {
    const addLink = vi.fn()
    const unavailable = vi.fn()
    const value = props({
      actions: [
        {
          id: 'link',
          kind: 'action',
          label: 'Add link',
          description: 'Reference a webpage',
          group: 'Context',
          onSelect: addLink,
        },
        {
          id: 'library',
          kind: 'action',
          label: 'Library',
          disabled: true,
          disabledReason: 'Library is not connected',
          group: 'Context',
          onSelect: unavailable,
        },
      ],
    })
    await render(value)
    await act(async () => button('Add context').click())
    const item = (label: string) =>
      [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((node) =>
        node.textContent?.startsWith(label),
      )!
    expect(item('Library').getAttribute('aria-disabled')).toBe('true')
    expect(item('Library').textContent).toContain('Library is not connected')
    await act(async () => item('Library').click())
    expect(unavailable).not.toHaveBeenCalled()
    await render({ ...value, busy: true })
    expect(item('Add link').getAttribute('aria-disabled')).toBe('true')
    await act(async () => item('Add link').click())
    expect(addLink).not.toHaveBeenCalled()
    await render(value)
    await act(async () => item('Add link').click())
    expect(addLink).toHaveBeenCalledExactlyOnceWith()
    expect(button('Add context').getAttribute('aria-expanded')).toBe('false')
  })

  it('removes selections by identity and lets only host-confirmed context enable empty submission', async () => {
    const value = props({
      value: '',
      selections: [
        { id: 'context-1', label: 'Brief', description: 'Reference text' },
        { id: 'tool-web', label: 'Web search' },
      ],
      onRemoveSelection: vi.fn(),
    })
    await render(value)
    expect(button('Send').disabled).toBe(true)
    await render({ ...value, hasContext: true })
    expect(button('Send').disabled).toBe(false)
    await act(async () => button('Remove selection: Brief').click())
    expect(value.onRemoveSelection).toHaveBeenCalledExactlyOnceWith('context-1')
    await pressEnter()
    expect(value.onSubmit).toHaveBeenCalledExactlyOnceWith()
    await render({ ...value, busy: true, hasContext: true })
    expect(button('Remove selection: Brief').disabled).toBe(true)
    expect(button('Remove selection: Web search').disabled).toBe(true)
  })

  it('returns keyboard focus to plus when its menu is dismissed with Escape', async () => {
    await render(props())
    const trigger = button('Add context')
    await act(async () => trigger.focus())
    await act(async () =>
      trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })),
    )
    const menu = document.querySelector<HTMLElement>('[role="menu"]')!
    expect(menu).not.toBeNull()
    await act(async () =>
      menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })),
    )
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger)
  })
})

describe('SegmentedTabs', () => {
  it('supports arrow-key navigation and references the supplied panel', async () => {
    const onValueChange = vi.fn()
    await act(async () =>
      root.render(
        createElement(SegmentedTabs, {
          value: 'chat',
          onValueChange,
          label: 'Mode',
          panelId: 'mode-panel',
          options: [
            { value: 'chat', label: 'Chat' },
            { value: 'task', label: 'Task' },
          ],
        }),
      ),
    )
    const tabs = container.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(tabs[0].getAttribute('aria-controls')).toBe('mode-panel')
    await act(async () => tabs[0].focus())
    await act(async () =>
      tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })),
    )
    expect(document.activeElement).toBe(tabs[1])
    expect(onValueChange).toHaveBeenCalledExactlyOnceWith('task')
  })
})
