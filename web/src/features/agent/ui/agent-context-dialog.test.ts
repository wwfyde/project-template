// @vitest-environment jsdom

import { act, createElement, createRef, useState, type ComponentProps } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createSkillClient, type Skill, type SkillList } from '../../skills'
import { agentActionsEn as copy } from '../model/action-translations'
import { AgentContextDialog } from './agent-context-dialog'

type DialogProps = ComponentProps<typeof AgentContextDialog>
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

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function skill(id: string, overrides: Partial<Skill> = {}): Skill {
  return {
    id,
    object: 'skill',
    name: id,
    description: `${id} description`,
    created_at: 1,
    default_version: '1',
    latest_version: '3',
    ...overrides,
  }
}

function page(data: Skill[], hasMore = false): SkillList<Skill> {
  return { object: 'list', data, has_more: hasMore, first_id: data[0]?.id ?? null, last_id: data.at(-1)?.id ?? null }
}

function clientFixture() {
  const request = vi.fn<(path: string, init?: RequestInit) => Promise<SkillList<Skill>>>()
  const client = createSkillClient({
    authenticatedRequest: async <T>(path: string, init?: RequestInit): Promise<T> => (await request(path, init)) as T,
  })
  return { request, client }
}

async function mount(overrides: Partial<DialogProps> = {}) {
  const fixture = clientFixture()
  fixture.request.mockResolvedValue(page([]))
  const props: DialogProps = {
    kind: 'skill',
    copy,
    existing: [],
    skillClient: fixture.client,
    onAdd: vi.fn(() => null),
    onClose: vi.fn(),
    returnFocusRef: createRef<HTMLTextAreaElement>(),
    ...overrides,
  }
  function Host() {
    const [open, setOpen] = useState(true)
    return createElement(
      'div',
      null,
      createElement('textarea', { ref: props.returnFocusRef, 'aria-label': 'Composer' }),
      open
        ? createElement(AgentContextDialog, {
            ...props,
            onClose: () => {
              props.onClose()
              setOpen(false)
            },
          })
        : null,
    )
  }
  await act(async () => root.render(createElement(Host)))
  return props
}

function dialog() {
  return document.querySelector<HTMLElement>('[role="dialog"]')!
}

function button(text: string) {
  const element = Array.from(dialog().querySelectorAll<HTMLButtonElement>('button')).find(
    (node) => node.textContent === text || node.getAttribute('aria-label') === text,
  )
  expect(element, `Button ${text}`).toBeDefined()
  return element!
}

function skillButton(name: string) {
  const element = Array.from(dialog().querySelectorAll<HTMLButtonElement>('button')).find((node) =>
    node.textContent?.includes(name),
  )
  expect(element, `Skill ${name}`).toBeDefined()
  return element!
}

function field(label: string): HTMLInputElement {
  const labelNode = Array.from(dialog().querySelectorAll('label')).find((node) => node.textContent?.includes(label))!
  return (
    labelNode.htmlFor ? document.getElementById(labelNode.htmlFor) : labelNode.querySelector('input')
  ) as HTMLInputElement
}

async function fill(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('AgentContextDialog skill catalog', () => {
  it('shows the loading state while GET is pending and then the real empty state', async () => {
    const { client, request } = clientFixture()
    const pending = deferred<SkillList<Skill>>()
    request.mockReturnValue(pending.promise)
    await mount({ skillClient: client })
    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][0]).toBe('/api/skills?limit=30&order=desc')
    expect(request.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal)
    expect(dialog().querySelector('[role="status"]')?.textContent).toContain(copy.skillLoading)
    expect(dialog().textContent).not.toContain(copy.skillEmpty)
    await act(async () => pending.resolve(page([])))
    expect(dialog().querySelector('[role="status"]')?.textContent).toBe(copy.skillEmpty)
    expect(dialog().textContent).not.toContain(copy.skillLoading)
  })

  it('reports service errors and retries the same GET instead of substituting demo skills', async () => {
    const { client, request } = clientFixture()
    request.mockRejectedValueOnce(new Error('Service unavailable')).mockResolvedValueOnce(page([skill('Recovered')]))
    const props = await mount({ skillClient: client })
    expect(dialog().querySelector('[role="alert"]')?.textContent).toBe(copy.skillError)
    expect(dialog().textContent).not.toContain(copy.skillEmpty)
    await act(async () => button(copy.skillRetry).click())
    expect(request).toHaveBeenCalledTimes(2)
    expect(request.mock.calls[1][0]).toBe(request.mock.calls[0][0])
    expect(skillButton('Recovered').disabled).toBe(false)
    expect(props.onAdd).not.toHaveBeenCalled()
    expect(props.onClose).not.toHaveBeenCalled()
  })

  it('retains loaded pages through a pagination error, searches loaded records, and adds the default version', async () => {
    const { client, request } = clientFixture()
    const next = deferred<SkillList<Skill>>()
    const retry = deferred<SkillList<Skill>>()
    request
      .mockResolvedValueOnce(page([skill('Alpha')], true))
      .mockReturnValueOnce(next.promise)
      .mockReturnValueOnce(retry.promise)
    const props = await mount({ skillClient: client })
    await act(async () => button(copy.skillMore).click())
    expect(request.mock.calls[1][0]).toBe('/api/skills?limit=30&order=desc&after=Alpha')
    expect(skillButton('Alpha').disabled).toBe(false)
    expect(dialog().textContent).toContain(copy.skillLoading)
    await act(async () => next.reject(new Error('Transient page failure')))
    expect(skillButton('Alpha').disabled).toBe(false)
    await act(async () => button(copy.skillRetry).click())
    expect(request.mock.calls[2][0]).toBe(request.mock.calls[1][0])
    await act(async () =>
      retry.resolve(
        page([
          skill('Alpha'),
          skill('Beta', { description: 'Planning work', default_version: '2', latest_version: '5' }),
        ]),
      ),
    )
    expect(
      Array.from(dialog().querySelectorAll('button')).filter((node) => node.textContent?.includes('Alpha')),
    ).toHaveLength(1)
    const search = field(copy.searchSkills)
    await fill(search, 'planning')
    expect(dialog().textContent).not.toContain('Alpha description')
    expect(skillButton('Beta').disabled).toBe(false)
    await fill(search, 'missing')
    expect(dialog().textContent).toContain(copy.skillNoMatch)
    await fill(search, 'planning')
    await act(async () => skillButton('Beta').click())
    expect(props.onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'skill', skillId: 'Beta', version: '2', title: 'Beta' }),
    )
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('disables already selected versions and unavailable skills, and keeps the dialog open on add rejection', async () => {
    const { client, request } = clientFixture()
    request.mockResolvedValue(page([skill('Selected'), skill('Unavailable', { default_version: '' }), skill('Other')]))
    const props = await mount({
      skillClient: client,
      existing: [
        {
          id: 'different-chip-id',
          kind: 'skill',
          title: 'Already selected',
          skillId: 'Selected',
          version: '1',
          description: '',
        },
      ],
      onAdd: vi.fn(() => copy.duplicate),
    })
    expect(skillButton('Selected').disabled).toBe(true)
    expect(skillButton('Selected').textContent).toContain(copy.skillSelected)
    expect(skillButton('Unavailable').disabled).toBe(true)
    await act(async () => skillButton('Selected').click())
    expect(props.onAdd).not.toHaveBeenCalled()
    await act(async () => skillButton('Other').click())
    expect(dialog().querySelector('[role="alert"]')?.textContent).toBe(copy.duplicate)
    expect(props.onClose).not.toHaveBeenCalled()
  })

  it('aborts the pending GET on close and ignores late results', async () => {
    const { client, request } = clientFixture()
    const pending = deferred<SkillList<Skill>>()
    request.mockReturnValue(pending.promise)
    const props = await mount({ skillClient: client })
    const signal = request.mock.calls[0][1]?.signal
    expect(signal?.aborted).toBe(false)
    await act(async () => button(copy.close).click())
    expect(signal?.aborted).toBe(true)
    expect(props.onClose).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(page([skill('Late result')])))
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(props.onAdd).not.toHaveBeenCalled()
  })
})

describe('AgentContextDialog web links', () => {
  it('validates URLs, preserves duplicate errors, and normalizes an accepted link with a default title', async () => {
    const onAdd = vi.fn<DialogProps['onAdd']>().mockReturnValueOnce(copy.duplicate).mockReturnValueOnce(null)
    const props = await mount({ kind: 'link', onAdd })
    expect(button(copy.add).disabled).toBe(true)
    const address = field(copy.url)
    for (const invalid of ['javascript:alert(1)', 'https://user:pass@example.com']) {
      await fill(address, invalid)
      await act(async () => button(copy.add).click())
      expect(dialog().querySelector('[role="alert"]')?.textContent).toBe(copy.invalidUrl)
      expect(address.getAttribute('aria-invalid')).toBe('true')
    }
    expect(onAdd).not.toHaveBeenCalled()
    await fill(address, 'HTTPS://Example.com:443/guide#intro')
    await act(async () => button(copy.add).click())
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'link', title: 'example.com', url: 'https://example.com/guide#intro' }),
    )
    expect(dialog().querySelector('[role="alert"]')?.textContent).toBe(copy.duplicate)
    expect(address.value).toBe('HTTPS://Example.com:443/guide#intro')
    expect(props.onClose).not.toHaveBeenCalled()
    await fill(address, 'https://example.com/other')
    await act(async () => button(copy.add).click())
    expect(onAdd).toHaveBeenCalledTimes(2)
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })
})
