import { afterEach, describe, expect, it, vi } from 'vitest'

import { startPreviewRun } from '../infrastructure/preview-transport'
import { MAX_CONTEXTS, type ContextReference } from './context'
import {
  createInitialWorkspace,
  getActiveConversation,
  MAX_ATTACHMENT_SIZE,
  validateAttachments,
  workspaceReducer,
  type AttachmentCandidate,
  type Workspace,
  type WorkspaceAction,
} from './workspace'

function submit(state: Workspace, text = 'Plan a launch', id = 'run-1'): Workspace {
  return workspaceReducer(workspaceReducer(state, { type: 'draft', patch: { text } }), { type: 'submit', id, now: 100 })
}

afterEach(() => vi.useRealTimers())

describe('agent workspace', () => {
  it('starts with an empty workspace and explicitly labelled, selectable examples', () => {
    const state = createInitialWorkspace('en')
    expect(getActiveConversation(state)).toBeUndefined()
    expect(state.conversations.every((conversation) => conversation.isExample)).toBe(true)
    const selected = workspaceReducer(state, { type: 'select', conversationId: 'example-1' })
    expect(selected.mode).toBe('task')
    expect(getActiveConversation(selected)?.messages).toHaveLength(2)
  })

  it('keeps each mode draft, attachments and settings independent', () => {
    let state = workspaceReducer(createInitialWorkspace('en'), {
      type: 'draft',
      patch: { text: 'Chat draft', modelId: 'focused', attachments: [{ id: 'a', name: 'notes.md', size: 10 }] },
    })
    state = workspaceReducer(state, { type: 'mode', mode: 'task' })
    state = workspaceReducer(state, { type: 'draft', patch: { text: 'Task draft', tools: ['research'] } })
    expect(state.drafts.chat.text).toBe('Chat draft')
    expect(state.drafts.chat.attachments).toHaveLength(1)
    expect(state.drafts.task.attachments).toEqual([])
    expect(state.drafts.task.modelId).toBe('auto')
    const sent = workspaceReducer(state, { type: 'submit', id: 'task-1', now: 42 })
    expect(sent.drafts.task).toEqual({ text: '', attachments: [], contexts: [], modelId: 'auto', tools: ['research'] })
    expect(sent.drafts.chat).toBe(state.drafts.chat)
  })

  it('submits selected attachment metadata without requiring text', () => {
    const attachment = { id: 'local-file', name: 'notes.md', size: 42 }
    const initial = workspaceReducer(createInitialWorkspace('en'), {
      type: 'draft',
      patch: { text: '  ', attachments: [attachment] },
    })
    const state = workspaceReducer(initial, { type: 'submit', id: 'file-run', now: 100 })
    expect(getActiveConversation(state)?.messages[0]).toMatchObject({
      content: 'Review the selected attachments',
      attachments: [attachment],
    })
    expect(state.drafts.chat.attachments).toEqual([])
    expect(state.drafts.chat.text).toBe('')
    expect(state.runs.chat?.prompt).toBe('Review the selected attachments')
  })

  it('captures model and tools for a run without following later draft changes', () => {
    let state = workspaceReducer(createInitialWorkspace('en'), {
      type: 'draft',
      patch: { modelId: 'fast', tools: ['web'] },
    })
    state = submit(state)
    const run = state.runs.chat!
    expect(run.tools).not.toBe(state.drafts.chat.tools)
    state = workspaceReducer(state, {
      type: 'draft',
      patch: { text: 'Next draft', modelId: 'thoughtful', tools: ['reasoning'] },
    })
    expect(state.runs.chat).toBe(run)
    expect(run).toMatchObject({ modelId: 'fast', tools: ['web'] })
    expect(state.drafts.chat).toMatchObject({ modelId: 'thoughtful', tools: ['reasoning'] })
  })

  it('rejects blank and duplicate submissions without clearing the next draft', () => {
    const initial = createInitialWorkspace('en')
    expect(workspaceReducer(initial, { type: 'submit', id: 'empty', now: 0 })).toBe(initial)
    let state = submit(initial)
    state = workspaceReducer(state, { type: 'draft', patch: { text: 'Next question' } })
    expect(workspaceReducer(state, { type: 'submit', id: 'duplicate', now: 1 })).toBe(state)
    expect(getActiveConversation(state)?.messages).toHaveLength(2)
  })

  it('retains partial output and the next draft when stopped, ignoring late events', () => {
    let state = submit(createInitialWorkspace('en'))
    state = workspaceReducer(state, {
      type: 'event',
      runId: 'run-1',
      event: { type: 'chunk', text: 'Partial preview' },
    })
    state = workspaceReducer(state, { type: 'draft', patch: { text: 'Next question' } })
    state = workspaceReducer(state, { type: 'stop' })
    expect(getActiveConversation(state)?.messages.at(-1)).toMatchObject({
      content: 'Partial preview',
      status: 'cancelled',
    })
    expect(state.drafts.chat.text).toBe('Next question')
    expect(workspaceReducer(state, { type: 'event', runId: 'run-1', event: { type: 'complete' } })).toBe(state)
  })

  it('keeps runs independent across mode changes and cancels the current mode on new', () => {
    let state = submit(createInitialWorkspace('zh-CN'))
    state = workspaceReducer(state, { type: 'mode', mode: 'task' })
    state = submit(state, '研究一个主题', 'run-2')
    expect(state.runs.chat?.id).toBe('run-1')
    expect(state.runs.task?.id).toBe('run-2')
    state = workspaceReducer(state, { type: 'new' })
    expect(state.runs.chat?.id).toBe('run-1')
    expect(state.runs.task).toBeNull()
    expect(getActiveConversation(state)).toBeUndefined()
    expect(
      state.conversations.find((conversation) => conversation.id === 'conversation-run-2')?.messages.at(-1)?.status,
    ).toBe('cancelled')
  })

  it('completes the correct background conversation and keeps its captured language', () => {
    let state = submit(createInitialWorkspace('zh-CN'))
    state = workspaceReducer(state, { type: 'language', language: 'en' })
    state = workspaceReducer(state, { type: 'mode', mode: 'task' })
    expect(state.runs.chat?.language).toBe('zh-CN')
    state = workspaceReducer(state, { type: 'event', runId: 'run-1', event: { type: 'chunk', text: '示例回复' } })
    state = workspaceReducer(state, { type: 'event', runId: 'run-1', event: { type: 'complete' } })
    expect(getActiveConversation(state, 'chat')?.messages.at(-1)).toMatchObject({
      content: '示例回复',
      status: 'completed',
    })
    expect(state.runs.chat).toBeNull()
    expect(state.mode).toBe('task')
  })
})

describe('workspace context selection', () => {
  const textContext = (id: string): ContextReference => ({
    id,
    kind: 'text',
    title: `Notes ${id}`,
    text: 'Local source text',
  })

  it('isolates contexts by mode, removes selected contexts and clears only the new mode', () => {
    let state = workspaceReducer(createInitialWorkspace('en'), { type: 'context-add', context: textContext('chat') })
    state = workspaceReducer(state, { type: 'context-add', mode: 'task', context: textContext('task') })
    state = workspaceReducer(state, { type: 'mode', mode: 'task' })
    expect(state.drafts.chat.contexts[0].id).toBe('chat')
    expect(state.drafts.task.contexts[0].id).toBe('task')
    state = workspaceReducer(state, { type: 'new' })
    expect(state.drafts.task.contexts).toEqual([])
    expect(state.drafts.chat.contexts).toHaveLength(1)
    state = workspaceReducer(state, { type: 'context-remove', mode: 'chat', id: 'chat' })
    expect(state.drafts.chat.contexts).toEqual([])
  })

  it('normalizes and deduplicates links and pinned skills before enforcing the selection limit', () => {
    const initial = createInitialWorkspace('en')
    let state = workspaceReducer(initial, {
      type: 'context-add',
      context: { id: 'link', kind: 'link', title: ' Source ', url: 'HTTPS://Example.com:443' },
    })
    expect(state.drafts.chat.contexts[0]).toMatchObject({ title: 'Source', url: 'https://example.com/' })
    expect(
      workspaceReducer(state, {
        type: 'context-add',
        context: { id: 'link-copy', kind: 'link', title: 'Duplicate', url: 'https://example.com/' },
      }),
    ).toBe(state)
    const skill: ContextReference = {
      id: 's1',
      kind: 'skill',
      title: 'Review',
      skillId: 'review',
      version: '1',
      description: '',
    }
    state = workspaceReducer(state, { type: 'context-add', context: skill })
    expect(workspaceReducer(state, { type: 'context-add', context: { ...skill, id: 's2' } })).toBe(state)
    state = workspaceReducer(state, { type: 'context-add', context: { ...skill, id: 's3', version: '2' } })
    for (let index = state.drafts.chat.contexts.length; index < MAX_CONTEXTS; index += 1) {
      state = workspaceReducer(state, { type: 'context-add', context: textContext(String(index)) })
    }
    expect(state.drafts.chat.contexts).toHaveLength(MAX_CONTEXTS)
    expect(workspaceReducer(state, { type: 'context-add', context: textContext('overflow') })).toBe(state)
  })

  it('rejects invalid or busy changes and prevents generic draft patches from bypassing validation', () => {
    const initial = createInitialWorkspace('en')
    const invalid: ContextReference = { id: 'invalid', kind: 'link', title: 'Unsafe', url: 'javascript:alert(1)' }
    expect(workspaceReducer(initial, { type: 'context-add', context: invalid })).toBe(initial)
    const injected = workspaceReducer(initial, {
      type: 'draft',
      patch: { contexts: [invalid] },
    } as unknown as WorkspaceAction)
    expect(injected.drafts.chat.contexts).toBe(initial.drafts.chat.contexts)
    const running = submit(initial)
    expect(workspaceReducer(running, { type: 'context-add', context: textContext('late') })).toBe(running)
    expect(workspaceReducer(running, { type: 'context-remove', id: 'late' })).toBe(running)
    expect(
      workspaceReducer(running, { type: 'context-add', mode: 'task', context: textContext('background') }).drafts.task
        .contexts,
    ).toHaveLength(1)
  })

  it('submits context without text and captures independent message and run snapshots', () => {
    for (const language of ['en', 'zh-CN'] as const) {
      const original = textContext('notes')
      let state = workspaceReducer(createInitialWorkspace(language), { type: 'context-add', context: original })
      const selected = state.drafts.chat.contexts[0]
      expect(selected).not.toBe(original)
      state = workspaceReducer(state, { type: 'submit', id: 'context-run', now: 100 })
      const message = getActiveConversation(state)!.messages[0]
      const run = state.runs.chat!
      expect(message.content).toBe(language === 'zh-CN' ? '参考所选上下文' : 'Review the selected context')
      expect(state.drafts.chat.contexts).toEqual([])
      expect(message.contexts).toEqual([original])
      expect(run.contexts).toEqual([original])
      expect(message.contexts![0]).not.toBe(selected)
      expect(run.contexts[0]).not.toBe(selected)
      expect(run.contexts[0]).not.toBe(message.contexts![0])
      selected.title = 'Changed later'
      expect(run.contexts[0].title).toBe('Notes notes')
    }
  })
})

describe('local attachment validation', () => {
  const file = (id: string, overrides: Partial<AttachmentCandidate> = {}): AttachmentCandidate => ({
    id,
    name: 'notes.md',
    type: '',
    size: 10,
    ...overrides,
  })

  it('accepts supported metadata, strips extra fields, and enforces size and type', () => {
    const result = validateAttachments(
      [],
      [
        file('ok', { size: MAX_ATTACHMENT_SIZE }),
        file('large', { size: MAX_ATTACHMENT_SIZE + 1 }),
        file('bad', { name: 'program.exe' }),
        file('image', { name: 'photo', type: 'image/png' }),
      ],
    )
    expect(result.accepted).toEqual([
      { id: 'ok', name: 'notes.md', size: MAX_ATTACHMENT_SIZE },
      { id: 'image', name: 'photo', size: 10 },
    ])
    expect(result.errors).toEqual(['too-large', 'unsupported'])
  })

  it('enforces the total file count and reports mixed-batch failures', () => {
    const existing = ['1', '2', '3', '4'].map((id) => file(id))
    const result = validateAttachments(existing, [file('5'), file('6'), file('7', { name: 'archive.zip' })])
    expect(result.accepted.map((attachment) => attachment.id)).toEqual(['5'])
    expect(result.errors).toEqual(['too-many', 'unsupported'])
    expect(existing).toHaveLength(4)
  })
})

describe('preview transport', () => {
  it('lists selected source titles without executing or echoing source instructions', () => {
    vi.useFakeTimers()
    for (const language of ['en', 'zh-CN'] as const) {
      const run = submit(createInitialWorkspace(language)).runs.chat!
      run.contexts = [
        { id: 'link', kind: 'link', title: 'Website', url: 'https://example.com' },
        { id: 'text', kind: 'text', title: 'Notes', text: 'EXECUTE_THIS_SOURCE_INSTRUCTION' },
        {
          id: 'skill',
          kind: 'skill',
          title: 'Review skill',
          skillId: 'review',
          version: '1',
          description: 'EXECUTE_THIS_SKILL_INSTRUCTION',
        },
      ]
      const onEvent = vi.fn()
      startPreviewRun(run, onEvent, new AbortController().signal)
      vi.runAllTimers()
      const answer = onEvent.mock.calls.map(([event]) => (event.type === 'chunk' ? event.text : '')).join('')
      expect(answer).toContain('Website')
      expect(answer).toContain('Notes')
      expect(answer).toContain('Review skill')
      expect(answer).toContain(language === 'zh-CN' ? '链接未抓取' : 'link not fetched')
      expect(answer).toContain(language === 'zh-CN' ? '技能未执行' : 'skill not executed')
      expect(answer).toContain(language === 'zh-CN' ? '文本仅供本地预览' : 'text is local preview only')
      expect(answer).not.toContain('EXECUTE_THIS')
    }
  })

  it('honors selected preview length and describes selected tools without claiming execution', () => {
    vi.useFakeTimers()
    for (const language of ['en', 'zh-CN'] as const) {
      const baseRun = submit(createInitialWorkspace(language)).runs.chat!
      const answers = ['fast', 'auto', 'thoughtful'].map((modelId) => {
        const onEvent = vi.fn()
        startPreviewRun({ ...baseRun, modelId, tools: ['web', 'reasoning'] }, onEvent, new AbortController().signal)
        vi.runAllTimers()
        return onEvent.mock.calls.map(([event]) => (event.type === 'chunk' ? event.text : '')).join('')
      })
      expect(answers[0].length).toBeLessThan(answers[1].length)
      expect(answers[1].length).toBeLessThan(answers[2].length)
      for (const answer of answers) {
        expect(answer).toContain(
          language === 'zh-CN'
            ? '联网搜索、深度思考（仅预览，未实际执行）'
            : 'Web search, Extended thinking (preview only; not executed)',
        )
      }
    }
  })

  it('emits local preview content and completes, without emitting after abort', () => {
    vi.useFakeTimers()
    const run = submit(createInitialWorkspace('en')).runs.chat!
    const onEvent = vi.fn()
    const controller = new AbortController()
    startPreviewRun(run, onEvent, controller.signal)
    vi.advanceTimersByTime(400)
    expect(onEvent).toHaveBeenCalled()
    controller.abort()
    const count = onEvent.mock.calls.length
    vi.runAllTimers()
    expect(onEvent).toHaveBeenCalledTimes(count)

    const complete = vi.fn()
    startPreviewRun(run, complete, new AbortController().signal)
    vi.runAllTimers()
    expect(complete.mock.calls.at(-1)?.[0]).toEqual({ type: 'complete' })
    expect(complete.mock.calls.map(([event]) => (event.type === 'chunk' ? event.text : '')).join('')).toContain(
      'No AI model, file reading or external search was used.',
    )
  })
})
