import { contextKey, MAX_CONTEXTS, normalizeContextUrl, validateContext, type ContextReference } from './context'

export type AgentMode = 'chat' | 'task'
export type AgentLanguage = 'zh-CN' | 'en'
export type MessageStatus = 'running' | 'completed' | 'cancelled' | 'error'
export type StepStatus = 'pending' | 'running' | 'completed'

export type Attachment = { id: string; name: string; size: number }
export type Draft = {
  text: string
  attachments: Attachment[]
  contexts: ContextReference[]
  modelId: string
  tools: string[]
}
export type TaskStep = { id: string; label: string; status: StepStatus }
export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  attachments?: Attachment[]
  contexts?: ContextReference[]
  status: MessageStatus
  steps?: TaskStep[]
}
export type Conversation = {
  id: string
  mode: AgentMode
  title: string
  messages: Message[]
  updatedAt: number
  isExample?: boolean
}
export type PreviewRun = {
  id: string
  conversationId: string
  assistantMessageId: string
  mode: AgentMode
  prompt: string
  language: AgentLanguage
  modelId: string
  tools: string[]
  contexts: ContextReference[]
}
export type PreviewEvent =
  | { type: 'chunk'; text: string }
  | { type: 'step'; index: number; status: StepStatus }
  | { type: 'complete' }
export type Workspace = {
  mode: AgentMode
  language: AgentLanguage
  drafts: Record<AgentMode, Draft>
  conversations: Conversation[]
  activeConversationIds: Record<AgentMode, string | null>
  runs: Record<AgentMode, PreviewRun | null>
}
export type WorkspaceAction =
  | { type: 'mode'; mode: AgentMode }
  | { type: 'language'; language: AgentLanguage }
  | { type: 'draft'; mode?: AgentMode; patch: Partial<Omit<Draft, 'contexts'>> }
  | { type: 'context-add'; mode?: AgentMode; context: ContextReference }
  | { type: 'context-remove'; mode?: AgentMode; id: string }
  | { type: 'submit'; id: string; now: number; mode?: AgentMode }
  | { type: 'event'; runId: string; event: PreviewEvent }
  | { type: 'stop'; mode?: AgentMode }
  | { type: 'new'; mode?: AgentMode }
  | { type: 'select'; conversationId: string }

const emptyDraft = (): Draft => ({ text: '', attachments: [], contexts: [], modelId: 'auto', tools: [] })

function normalizedContext(context: ContextReference): ContextReference {
  const title = context.title.trim()
  if (context.kind === 'link') return { ...context, title, url: normalizeContextUrl(context.url)! }
  if (context.kind === 'skill')
    return { ...context, title, skillId: context.skillId.trim(), version: context.version.trim() }
  return { ...context, title }
}

function sameContext(left: ContextReference, right: ContextReference): boolean {
  return left.id === right.id || contextKey(left) === contextKey(right)
}

function createSteps(language: AgentLanguage, runId: string): TaskStep[] {
  const labels =
    language === 'zh-CN'
      ? ['整理任务目标', '组织示例计划', '准备预览结果']
      : ['Outline the goal', 'Build an example plan', 'Prepare the preview']
  return labels.map((label, index) => ({
    id: `${runId}-step-${index}`,
    label,
    status: index === 0 ? 'running' : 'pending',
  }))
}

export function createInitialWorkspace(language: AgentLanguage): Workspace {
  const examples =
    language === 'zh-CN'
      ? [
          {
            mode: 'chat' as const,
            title: '把灵感变成清晰的表达',
            question: '如何把一个模糊的想法整理成方案？',
            answer:
              '这是一段示例对话。先用一句话说明你想解决的问题，再列出目标人群、使用场景和完成标准。最后写下最小可行的下一步，让想法可以被验证。',
          },
          {
            mode: 'task' as const,
            title: '规划一次产品调研',
            question: '帮我规划一次新产品的用户调研。',
            answer:
              '示例计划已整理。\n\n1. 明确这次调研需要回答的三个问题。\n2. 选择目标用户，准备开放式访谈提纲。\n3. 按共同问题汇总发现，形成下一步验证清单。\n\n这里只展示任务界面，没有访问外部资料或执行真实任务。',
          },
          {
            mode: 'chat' as const,
            title: '让每周工作更有条理',
            question: '给我一个简单的周计划方法。',
            answer:
              '这是一段示例对话。每周先选三件最重要的事，为每件事留出具体时间，并记录完成标准。每天结束时检查进展，给临时工作保留余量。',
          },
        ]
      : [
          {
            mode: 'chat' as const,
            title: 'Turn an idea into a clear brief',
            question: 'How can I turn a rough idea into a plan?',
            answer:
              'This is an example conversation. Describe the problem in one sentence, then identify the audience, context and success criteria. Finish with one small next step you can validate.',
          },
          {
            mode: 'task' as const,
            title: 'Plan a product research project',
            question: 'Help me plan user research for a new product.',
            answer:
              'Here is an example plan.\n\n1. Define the three questions the research should answer.\n2. Choose participants and prepare open-ended interview questions.\n3. Group the findings and list the next ideas to validate.\n\nThis is a UI preview. No external research or real tasks were performed.',
          },
          {
            mode: 'chat' as const,
            title: 'Make room for focused work',
            question: 'Suggest a simple weekly planning method.',
            answer:
              'This is an example conversation. Choose three priorities, reserve time for each, and define what finished means. Review your progress at the end of the day and leave room for unexpected work.',
          },
        ]

  return {
    mode: 'chat',
    language,
    drafts: { chat: emptyDraft(), task: emptyDraft() },
    conversations: examples.map((example, index) => ({
      id: `example-${index}`,
      mode: example.mode,
      title: example.title,
      updatedAt: 0,
      isExample: true,
      messages: [
        { id: `example-${index}-user`, role: 'user', content: example.question, status: 'completed' },
        {
          id: `example-${index}-assistant`,
          role: 'assistant',
          content: example.answer,
          status: 'completed',
          ...(example.mode === 'task'
            ? {
                steps: createSteps(language, `example-${index}`).map((step) => ({
                  ...step,
                  status: 'completed' as const,
                })),
              }
            : {}),
        },
      ],
    })),
    activeConversationIds: { chat: null, task: null },
    runs: { chat: null, task: null },
  }
}

export function getActiveConversation(state: Workspace, mode = state.mode): Conversation | undefined {
  return state.conversations.find((conversation) => conversation.id === state.activeConversationIds[mode])
}

function updateRunMessage(state: Workspace, run: PreviewRun, update: (message: Message) => Message): Conversation[] {
  return state.conversations.map((conversation) =>
    conversation.id === run.conversationId
      ? {
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === run.assistantMessageId ? update(message) : message,
          ),
        }
      : conversation,
  )
}

function stopRun(state: Workspace, mode: AgentMode): Workspace {
  const run = state.runs[mode]
  if (!run) return state
  return {
    ...state,
    conversations: updateRunMessage(state, run, (message) => ({ ...message, status: 'cancelled' })),
    runs: { ...state.runs, [mode]: null },
  }
}

export function workspaceReducer(state: Workspace, action: WorkspaceAction): Workspace {
  switch (action.type) {
    case 'mode':
      return { ...state, mode: action.mode }
    case 'language':
      return { ...state, language: action.language }
    case 'draft': {
      const mode = action.mode ?? state.mode
      // Context changes go through the validated actions, including at runtime.
      return {
        ...state,
        drafts: {
          ...state.drafts,
          [mode]: { ...state.drafts[mode], ...action.patch, contexts: state.drafts[mode].contexts },
        },
      }
    }
    case 'context-add': {
      const mode = action.mode ?? state.mode
      const draft = state.drafts[mode]
      if (state.runs[mode] || validateContext(action.context) || draft.contexts.length >= MAX_CONTEXTS) return state
      const context = normalizedContext(action.context)
      if (draft.contexts.some((existing) => sameContext(existing, context))) return state
      return { ...state, drafts: { ...state.drafts, [mode]: { ...draft, contexts: [...draft.contexts, context] } } }
    }
    case 'context-remove': {
      const mode = action.mode ?? state.mode
      const draft = state.drafts[mode]
      if (state.runs[mode] || !draft.contexts.some((context) => context.id === action.id)) return state
      return {
        ...state,
        drafts: {
          ...state.drafts,
          [mode]: { ...draft, contexts: draft.contexts.filter((context) => context.id !== action.id) },
        },
      }
    }
    case 'submit': {
      const mode = action.mode ?? state.mode
      const draft = state.drafts[mode]
      const text = draft.text.trim()
      if ((!text && draft.attachments.length === 0 && draft.contexts.length === 0) || state.runs[mode]) return state
      const prompt =
        text ||
        (draft.contexts.length > 0
          ? state.language === 'zh-CN'
            ? '参考所选上下文'
            : 'Review the selected context'
          : state.language === 'zh-CN'
            ? '查看所选附件'
            : 'Review the selected attachments')
      const active = getActiveConversation(state, mode)
      const conversationId = active?.id ?? `conversation-${action.id}`
      const assistantMessageId = `${action.id}-assistant`
      const messages: Message[] = [
        {
          id: `${action.id}-user`,
          role: 'user',
          content: prompt,
          attachments: [...draft.attachments],
          contexts: draft.contexts.map((context) => ({ ...context })),
          status: 'completed',
        },
        {
          id: assistantMessageId,
          role: 'assistant',
          content: '',
          status: 'running',
          ...(mode === 'task' ? { steps: createSteps(state.language, action.id) } : {}),
        },
      ]
      const conversation: Conversation = {
        id: conversationId,
        mode,
        title: active?.title ?? Array.from(prompt.replace(/\s+/g, ' ')).slice(0, 40).join(''),
        messages: [...(active?.messages ?? []), ...messages],
        updatedAt: action.now,
        ...(active?.isExample ? { isExample: true } : {}),
      }
      return {
        ...state,
        conversations: [conversation, ...state.conversations.filter((item) => item.id !== conversationId)],
        activeConversationIds: { ...state.activeConversationIds, [mode]: conversationId },
        drafts: { ...state.drafts, [mode]: { ...draft, text: '', attachments: [], contexts: [] } },
        runs: {
          ...state.runs,
          [mode]: {
            id: action.id,
            conversationId,
            assistantMessageId,
            mode,
            prompt,
            language: state.language,
            modelId: draft.modelId,
            tools: [...draft.tools],
            contexts: draft.contexts.map((context) => ({ ...context })),
          },
        },
      }
    }
    case 'event': {
      const run = Object.values(state.runs).find((candidate) => candidate?.id === action.runId)
      if (!run) return state
      const event = action.event
      return {
        ...state,
        conversations: updateRunMessage(state, run, (message) => {
          if (event.type === 'chunk') return { ...message, content: message.content + event.text }
          if (event.type === 'step')
            return {
              ...message,
              steps: message.steps?.map((step, index) =>
                index === event.index ? { ...step, status: event.status } : step,
              ),
            }
          return {
            ...message,
            status: 'completed',
            steps: message.steps?.map((step) => ({ ...step, status: 'completed' })),
          }
        }),
        runs: event.type === 'complete' ? { ...state.runs, [run.mode]: null } : state.runs,
      }
    }
    case 'stop':
      return stopRun(state, action.mode ?? state.mode)
    case 'new': {
      const mode = action.mode ?? state.mode
      const stopped = stopRun(state, mode)
      return {
        ...stopped,
        mode,
        activeConversationIds: { ...stopped.activeConversationIds, [mode]: null },
        drafts: { ...stopped.drafts, [mode]: { ...stopped.drafts[mode], text: '', attachments: [], contexts: [] } },
      }
    }
    case 'select': {
      const conversation = state.conversations.find((item) => item.id === action.conversationId)
      if (!conversation) return state
      const stopped =
        state.activeConversationIds[conversation.mode] === conversation.id ? state : stopRun(state, conversation.mode)
      return {
        ...stopped,
        mode: conversation.mode,
        activeConversationIds: { ...stopped.activeConversationIds, [conversation.mode]: conversation.id },
      }
    }
  }
}

export type AttachmentCandidate = Attachment & { type: string }
export type AttachmentError = 'too-many' | 'too-large' | 'unsupported'
export const MAX_ATTACHMENTS = 5
export const MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
export const ATTACHMENT_ACCEPT = 'image/*,.pdf,.txt,.md,.csv,.json'

export function validateAttachments(
  existing: Attachment[],
  candidates: AttachmentCandidate[],
): {
  accepted: Attachment[]
  errors: AttachmentError[]
} {
  const accepted: Attachment[] = []
  const errors = new Set<AttachmentError>()
  for (const candidate of candidates) {
    const extension = candidate.name.split('.').at(-1)?.toLowerCase()
    if (
      !candidate.type.startsWith('image/') &&
      ![
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'avif',
        'heic',
        'heif',
        'bmp',
        'svg',
        'pdf',
        'txt',
        'md',
        'csv',
        'json',
      ].includes(extension ?? '')
    ) {
      errors.add('unsupported')
    } else if (!Number.isFinite(candidate.size) || candidate.size < 0 || candidate.size > MAX_ATTACHMENT_SIZE) {
      errors.add('too-large')
    } else if (existing.length + accepted.length >= MAX_ATTACHMENTS) {
      errors.add('too-many')
    } else if (![...existing, ...accepted].some((attachment) => attachment.id === candidate.id)) {
      accepted.push({ id: candidate.id, name: candidate.name, size: candidate.size })
    }
  }
  return { accepted, errors: [...errors] }
}
