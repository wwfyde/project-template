import {
  ArrowUpRight,
  BookOpen,
  Brain,
  CircleDashed,
  Code2,
  Compass,
  Feather,
  FileText,
  Globe,
  Languages,
  Link2,
  ListChecks,
  MessageCircle,
  Moon,
  PanelLeft,
  Search,
  Sparkles,
  SquarePen,
  Sun,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ChatComposer } from '../../../blocks/chat-composer'
import { IconButton } from '../../../components/ui/icon-button'
import { SegmentedTabs } from '../../../components/ui/segmented-tabs'
import { Sheet } from '../../../components/ui/sheet'
import { useTheme } from '../../../theme'
import { useAuth } from '../../auth'
import { createSkillClient } from '../../skills'
import { startPreviewRun } from '../infrastructure/preview-transport'
import { agentActionsEn, agentActionsZhCN } from '../model/action-translations'
import { MAX_CONTEXTS, contextKey, validateContext, type ContextReference } from '../model/context'
import { agentEn, agentZhCN } from '../model/translations'
import {
  createInitialWorkspace,
  getActiveConversation,
  validateAttachments,
  workspaceReducer,
  type AgentMode,
  type PreviewRun,
  type WorkspaceAction,
} from '../model/workspace'
import { AgentSidebar } from './agent-sidebar'
import { AgentTranscript } from './agent-transcript'
import { AgentContextDialog, type ContextDialogKind } from './agent-context-dialog'
import './agent.css'

function usePreviewRun(run: PreviewRun | null, dispatch: React.Dispatch<WorkspaceAction>) {
  useEffect(() => {
    if (!run) return
    const controller = new AbortController()
    startPreviewRun(run, (event) => dispatch({ type: 'event', runId: run.id, event }), controller.signal)
    return () => controller.abort()
  }, [run, dispatch])
}

export function AgentPage() {
  const { i18n } = useTranslation()
  const language = i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en'
  const copy = language === 'zh-CN' ? agentZhCN : agentEn
  const actionCopy = language === 'zh-CN' ? agentActionsZhCN : agentActionsEn
  const { user, authenticatedRequest } = useAuth()
  const skillClient = useMemo(() => createSkillClient({ authenticatedRequest }), [authenticatedRequest])
  const { resolvedMode, setPreferences } = useTheme()
  const [state, dispatch] = useReducer(workspaceReducer, language, createInitialWorkspace)
  const [sidebarVisible, setSidebarVisible] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const mobileSidebarTriggerRef = useRef<HTMLButtonElement>(null)
  const composerInputRef = useRef<HTMLTextAreaElement>(null)
  const [contextDialog, setContextDialog] = useState<{ kind: ContextDialogKind; mode: AgentMode } | null>(null)
  const [errors, setErrors] = useState<Record<AgentMode, string>>({ chat: '', task: '' })
  const mode = state.mode
  const draft = state.drafts[mode]
  const conversation = getActiveConversation(state)
  const busy = Boolean(state.runs[mode])
  usePreviewRun(state.runs.chat, dispatch)
  usePreviewRun(state.runs.task, dispatch)

  useEffect(() => {
    dispatch({ type: 'language', language })
  }, [language])
  const newConversation = useCallback(() => {
    dispatch({ type: 'new' })
    setErrors({ chat: '', task: '' })
    setMobileSidebarOpen(false)
    requestAnimationFrame(() => composerInputRef.current?.focus())
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!contextDialog && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        newConversation()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [newConversation, contextDialog])

  const openContext = (kind: ContextDialogKind) => {
    // Let the menu finish returning focus before the modal takes it.
    requestAnimationFrame(() => setContextDialog({ kind, mode }))
  }
  const addContext = (reference: ContextReference): string | null => {
    const targetMode = contextDialog?.mode ?? mode
    const existing = state.drafts[targetMode].contexts
    if (state.runs[targetMode]) return actionCopy.busy
    const error = validateContext(reference)
    if (error === 'invalid-url') return actionCopy.invalidUrl
    if (error === 'invalid-title') return actionCopy.invalidTitle
    if (error === 'empty-text') return actionCopy.emptyText
    if (error === 'text-too-long') return actionCopy.textTooLong
    if (error) return actionCopy.invalidContext
    if (existing.some((item) => contextKey(item) === contextKey(reference))) return actionCopy.duplicate
    if (existing.length >= MAX_CONTEXTS) return actionCopy.tooMany
    dispatch({ type: 'context-add', mode: targetMode, context: reference })
    return null
  }

  const addFiles = (files: File[]) => {
    const result = validateAttachments(
      draft.attachments,
      files.map((file) => ({ id: crypto.randomUUID(), name: file.name, size: file.size, type: file.type })),
    )
    const messages = { 'too-many': copy.fileTooMany, 'too-large': copy.fileTooLarge, unsupported: copy.fileUnsupported }
    setErrors((current) => ({ ...current, [mode]: result.errors.map((error) => messages[error]).join(' ') }))
    dispatch({ type: 'draft', patch: { attachments: [...draft.attachments, ...result.accepted] } })
  }

  const sidebarProps = {
    copy,
    conversations: state.conversations,
    activeId: conversation?.id,
    userName: user?.display_name || 'You',
    onNew: newConversation,
    onSelect: (conversationId: string) => {
      dispatch({ type: 'select', conversationId })
      setMobileSidebarOpen(false)
    },
  }
  const suggestions = mode === 'chat' ? copy.chatSuggestions : copy.taskSuggestions
  const suggestionIcons = mode === 'chat' ? [Compass, Feather, BookOpen, Code2] : [Search, ListChecks, Feather, Code2]
  const composer = (
    <ChatComposer
      inputRef={composerInputRef}
      value={draft.text}
      onValueChange={(text) => dispatch({ type: 'draft', patch: { text } })}
      attachments={draft.attachments}
      onFilesAdded={addFiles}
      onRemoveAttachment={(id) => {
        dispatch({ type: 'draft', patch: { attachments: draft.attachments.filter((file) => file.id !== id) } })
        setErrors((current) => ({ ...current, [mode]: '' }))
      }}
      modelId={draft.modelId}
      models={[
        { id: 'auto', label: copy.auto, description: copy.autoDescription },
        { id: 'thoughtful', label: copy.thoughtful, description: copy.thoughtfulDescription },
        { id: 'fast', label: copy.fast, description: copy.fastDescription },
      ]}
      onModelChange={(modelId) => dispatch({ type: 'draft', patch: { modelId } })}
      actions={[
        {
          id: 'link',
          kind: 'action',
          label: actionCopy.addLink,
          description: actionCopy.linkDescription,
          icon: <Link2 size={18} />,
          group: actionCopy.contextGroup,
          disabled: draft.contexts.length >= MAX_CONTEXTS,
          disabledReason: draft.contexts.length >= MAX_CONTEXTS ? actionCopy.tooMany : undefined,
          onSelect: () => openContext('link'),
        },
        {
          id: 'text',
          kind: 'action',
          label: actionCopy.addText,
          description: actionCopy.textDescription,
          icon: <FileText size={18} />,
          group: actionCopy.contextGroup,
          disabled: draft.contexts.length >= MAX_CONTEXTS,
          disabledReason: draft.contexts.length >= MAX_CONTEXTS ? actionCopy.tooMany : undefined,
          onSelect: () => openContext('text'),
        },
        {
          id: 'skill',
          kind: 'action',
          label: actionCopy.addSkill,
          description: actionCopy.skillDescription,
          icon: <CircleDashed size={18} />,
          group: actionCopy.contextGroup,
          disabled: draft.contexts.length >= MAX_CONTEXTS,
          disabledReason: draft.contexts.length >= MAX_CONTEXTS ? actionCopy.tooMany : undefined,
          onSelect: () => openContext('skill'),
        },
        {
          id: 'mode',
          kind: 'action',
          label: mode === 'chat' ? actionCopy.switchTask : actionCopy.switchChat,
          description: actionCopy.switchDescription,
          icon: <ListChecks size={18} />,
          group: actionCopy.modeGroup,
          onSelect: () => {
            dispatch({ type: 'mode', mode: mode === 'chat' ? 'task' : 'chat' })
            requestAnimationFrame(() => composerInputRef.current?.focus())
          },
        },
      ]}
      tools={[
        {
          id: 'web',
          label: copy.web,
          description: actionCopy.webDescription,
          icon: <Globe size={18} />,
          enabled: draft.tools.includes('web'),
        },
        {
          id: 'reasoning',
          label: copy.reasoning,
          description: actionCopy.reasoningDescription,
          icon: <Brain size={18} />,
          enabled: draft.tools.includes('reasoning'),
        },
      ]}
      selections={[
        ...draft.contexts.map((reference) => ({
          id: `context:${reference.id}`,
          label: reference.title,
          description:
            reference.kind === 'link'
              ? reference.url
              : reference.kind === 'skill'
                ? `${actionCopy.skill} · v${reference.version}`
                : actionCopy.note,
          icon:
            reference.kind === 'link' ? (
              <Link2 size={14} />
            ) : reference.kind === 'skill' ? (
              <CircleDashed size={14} />
            ) : (
              <FileText size={14} />
            ),
        })),
        ...draft.tools.map((tool) => ({
          id: `tool:${tool}`,
          label: tool === 'web' ? copy.web : copy.reasoning,
          description: actionCopy.preview,
          icon: tool === 'web' ? <Globe size={14} /> : <Brain size={14} />,
        })),
      ]}
      hasContext={draft.contexts.length > 0}
      onRemoveSelection={(id) => {
        if (id.startsWith('context:')) dispatch({ type: 'context-remove', id: id.slice(8) })
        else dispatch({ type: 'draft', patch: { tools: draft.tools.filter((tool) => `tool:${tool}` !== id) } })
      }}
      onToolToggle={(id) =>
        dispatch({
          type: 'draft',
          patch: { tools: draft.tools.includes(id) ? draft.tools.filter((tool) => tool !== id) : [...draft.tools, id] },
        })
      }
      busy={busy}
      onSubmit={() => {
        setErrors((current) => ({ ...current, [mode]: '' }))
        dispatch({ type: 'submit', id: crypto.randomUUID(), now: Date.now() })
        requestAnimationFrame(() => composerInputRef.current?.focus())
      }}
      onStop={() => dispatch({ type: 'stop' })}
      labels={{
        ...copy,
        addContext: actionCopy.addContext,
        actionsHint: actionCopy.actionsHint,
        removeSelection: actionCopy.removeSelection,
        uploadDescription: actionCopy.uploadDescription,
        placeholder: mode === 'chat' ? copy.chatPlaceholder : copy.taskPlaceholder,
        submit: mode === 'chat' ? copy.submit : copy.startTask,
      }}
      error={errors[mode]}
      context={
        mode === 'task' ? (
          <span className="inline-flex items-center gap-2 rounded-lg bg-agent-subtle px-2.5 py-1.5 text-[11px] text-agent-muted">
            <ListChecks size={13} />
            {copy.taskContext}
          </span>
        ) : undefined
      }
    />
  )

  return (
    <div className="agent-workspace flex">
      {contextDialog ? (
        <AgentContextDialog
          key={`${contextDialog.mode}-${contextDialog.kind}`}
          kind={contextDialog.kind}
          copy={actionCopy}
          existing={state.drafts[contextDialog.mode].contexts}
          skillClient={skillClient}
          onAdd={addContext}
          onClose={() => setContextDialog(null)}
          returnFocusRef={composerInputRef}
        />
      ) : null}
      {sidebarVisible ? (
        <aside className="hidden w-[252px] shrink-0 md:block">
          <AgentSidebar {...sidebarProps} onClose={() => setSidebarVisible(false)} />
        </aside>
      ) : null}
      <Sheet
        open={mobileSidebarOpen}
        onOpenChange={setMobileSidebarOpen}
        title={copy.workspace}
        closeLabel={copy.closeSidebar}
        returnFocusRef={mobileSidebarTriggerRef}
      >
        <AgentSidebar {...sidebarProps} />
      </Sheet>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[72px] shrink-0 items-center justify-between gap-3 px-4 sm:px-7">
          <div className="flex min-w-0 items-center gap-2">
            <IconButton
              ref={mobileSidebarTriggerRef}
              label={copy.openSidebar}
              onClick={() => setMobileSidebarOpen(true)}
              className="md:hidden"
            >
              <PanelLeft size={19} strokeWidth={1.7} />
            </IconButton>
            {!sidebarVisible ? (
              <IconButton
                label={copy.openSidebar}
                onClick={() => setSidebarVisible(true)}
                className="hidden md:inline-flex"
              >
                <PanelLeft size={19} strokeWidth={1.7} />
              </IconButton>
            ) : null}
            <span className="text-[18px] font-semibold tracking-tight">Agent</span>
            <span className="ml-1 hidden rounded-md border border-agent-border px-2 py-0.5 text-[10px] text-agent-muted sm:block">
              {copy.preview}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {conversation ? (
              <IconButton label={copy.newChat} onClick={newConversation}>
                <SquarePen size={17} strokeWidth={1.6} />
              </IconButton>
            ) : null}
            <IconButton
              label={copy.language}
              onClick={() => void i18n.changeLanguage(language === 'zh-CN' ? 'en' : 'zh-CN')}
            >
              <Languages size={18} strokeWidth={1.6} />
            </IconButton>
            <IconButton
              label={resolvedMode === 'dark' ? copy.light : copy.dark}
              onClick={() => setPreferences({ mode: resolvedMode === 'dark' ? 'light' : 'dark' })}
            >
              {resolvedMode === 'dark' ? <Sun size={18} strokeWidth={1.6} /> : <Moon size={18} strokeWidth={1.6} />}
            </IconButton>
          </div>
        </header>

        <div className={`flex shrink-0 justify-center ${conversation ? 'pb-2' : 'pt-3 sm:pt-6'}`}>
          <SegmentedTabs<AgentMode>
            value={mode}
            onValueChange={(next) => dispatch({ type: 'mode', mode: next })}
            label={copy.modes}
            panelId="agent-mode-panel"
            options={[
              { value: 'chat', label: copy.chat, icon: <MessageCircle size={15} strokeWidth={1.7} /> },
              { value: 'task', label: copy.task, icon: <ListChecks size={16} strokeWidth={1.7} /> },
            ]}
          />
        </div>

        <div
          id="agent-mode-panel"
          role="tabpanel"
          aria-labelledby={`agent-mode-panel-tab-${mode}`}
          className="flex min-h-0 flex-1 flex-col"
        >
          {conversation ? (
            <>
              <AgentTranscript conversation={conversation} copy={copy} contextCopy={actionCopy} />
              <div className="agent-composer-dock shrink-0 px-4 pt-4 sm:px-10">
                <div className="mx-auto max-w-[760px]">
                  {composer}
                  <p className="mt-3 text-center text-[10px] text-agent-muted sm:text-[11px]">{copy.localHint}</p>
                </div>
              </div>
            </>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 sm:px-10">
              <div className="agent-welcome">
                <div className="mb-8 text-center sm:mb-9">
                  <span className="mb-5 inline-flex size-12 items-center justify-center rounded-2xl border border-agent-border bg-agent-surface shadow-[0_2px_12px_#00000003]">
                    <Sparkles size={24} strokeWidth={1.45} />
                  </span>
                  <p className="mb-3 text-[11px] tracking-wider text-agent-muted">{copy.eyebrow}</p>
                  <h1 className="text-[clamp(26px,3vw,36px)] font-medium leading-[1.35] tracking-[-0.035em]">
                    {mode === 'chat' ? copy.greeting : copy.taskGreeting}
                  </h1>
                  <p className="mt-3 text-[13px] leading-6 text-agent-muted">
                    {mode === 'chat' ? copy.chatDescription : copy.taskDescription}
                  </p>
                </div>
                {composer}
                <section className="mt-8 sm:mt-9" aria-label={copy.suggestions}>
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
                    {suggestions.map((suggestion, index) => {
                      const SuggestionIcon = suggestionIcons[index]
                      return (
                        <button
                          type="button"
                          key={suggestion.title}
                          aria-label={suggestion.title}
                          className="group flex min-w-0 flex-col items-start rounded-2xl border border-agent-border bg-agent-canvas p-4 text-left transition-colors hover:bg-agent-sidebar"
                          onClick={() => {
                            dispatch({ type: 'draft', patch: { text: suggestion.prompt } })
                            requestAnimationFrame(() => composerInputRef.current?.focus())
                          }}
                        >
                          <div className="mb-4 flex w-full items-center justify-between">
                            <SuggestionIcon size={18} strokeWidth={1.6} className="text-agent-muted" />
                            <ArrowUpRight
                              size={13}
                              className="text-agent-muted opacity-0 transition-opacity group-hover:opacity-100"
                            />
                          </div>
                          <p className="text-[13px] font-medium">{suggestion.title}</p>
                          <p className="mt-1.5 text-[11px] leading-5 text-agent-muted">{suggestion.description}</p>
                        </button>
                      )
                    })}
                  </div>
                </section>
              </div>
              <p className="shrink-0 pb-5 text-center text-[10px] text-agent-muted sm:text-[11px]">{copy.localHint}</p>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
