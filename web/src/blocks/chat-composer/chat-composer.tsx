import { ArrowUp, Check, ChevronDown, FileText, Paperclip, SlidersHorizontal, Square, Upload, X } from 'lucide-react'
import { useId, useRef, useState } from 'react'

import { AutoTextarea } from '../../components/ui/auto-textarea'
import { IconButton } from '../../components/ui/icon-button'
import { Menu, MenuContent, MenuRadioGroup, MenuRadioItem, MenuTrigger } from '../../components/ui/menu'
import { ComposerActionMenu } from './composer-action-menu'
import type { ChatComposerProps } from './types'

const triggerClassName =
  'inline-flex min-h-control min-w-0 items-center justify-center gap-1.5 rounded-control px-3 text-[13px] text-muted-foreground transition-colors duration-(--motion-duration) ease-(--motion-easing) hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring data-disabled:opacity-40'

function fileSize(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ChatComposer({
  value,
  onValueChange,
  attachments,
  onFilesAdded,
  onRemoveAttachment,
  modelId,
  models,
  onModelChange,
  tools,
  onToolToggle,
  actions = [],
  selections = [],
  onRemoveSelection,
  hasContext = false,
  inputRef,
  actionTriggerRef,
  busy,
  onSubmit,
  onStop,
  labels,
  context,
  accept = 'image/*,.pdf,.txt,.md,.csv,.json',
  error,
  className = '',
}: ChatComposerProps) {
  const id = useId()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const composing = useRef(false)
  const dragDepth = useRef(0)
  const [isDragging, setIsDragging] = useState(false)
  const canSubmit = !busy && Boolean(value.trim() || attachments.length || hasContext)
  const activeModel = models.find((model) => model.id === modelId)

  const addFiles = (files: File[]) => {
    if (!busy && files.length > 0) onFilesAdded(files)
  }

  return (
    <div className={`w-full min-w-0 ${className}`}>
      <form
        aria-label={labels.input}
        data-slot="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
        onDragEnter={(event) => {
          if (!event.dataTransfer.types.includes('Files')) return
          event.preventDefault()
          dragDepth.current += 1
          if (!busy) setIsDragging(true)
        }}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes('Files')) event.preventDefault()
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (!dragDepth.current) setIsDragging(false)
        }}
        onDrop={(event) => {
          event.preventDefault()
          dragDepth.current = 0
          setIsDragging(false)
          addFiles(Array.from(event.dataTransfer.files))
        }}
        className="relative rounded-panel border border-border bg-card p-3 shadow-panel backdrop-blur-surface transition-shadow duration-(--motion-duration) ease-(--motion-easing) focus-within:ring-1 focus-within:ring-ring"
      >
        <div data-slot="composer-input" className="min-h-0">
          {context ? <div className="px-2 pb-2 pt-1">{context}</div> : null}

          {selections.length > 0 ? (
            <div
              className="flex max-h-28 flex-wrap gap-2 overflow-y-auto px-2 pb-2 pt-1"
              data-slot="composer-selections"
            >
              {selections.map((selection) => (
                <span
                  key={selection.id}
                  title={selection.description ?? selection.label}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-control border border-border bg-muted py-1 pl-2.5 pr-1.5 text-xs text-foreground"
                >
                  {selection.icon ? (
                    <span className="flex shrink-0 items-center text-muted-foreground" aria-hidden="true">
                      {selection.icon}
                    </span>
                  ) : null}
                  <span className="max-w-52 truncate">{selection.label}</span>
                  {onRemoveSelection ? (
                    <IconButton
                      label={`${labels.removeSelection ?? labels.removeAttachment}: ${selection.label}`}
                      disabled={busy}
                      onClick={() => onRemoveSelection(selection.id)}
                      size="xs"
                    >
                      <X size={12} aria-hidden="true" />
                    </IconButton>
                  ) : null}
                </span>
              ))}
            </div>
          ) : null}

          {attachments.length > 0 ? (
            <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto px-2 pb-2 pt-1">
              {attachments.map((attachment) => (
                <div
                  key={attachment.id}
                  className="flex max-w-full items-center gap-2 rounded-control border border-border px-2 py-1.5 text-foreground"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-control bg-muted">
                    <FileText size={17} strokeWidth={1.7} aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <p className="max-w-40 truncate text-xs font-medium" title={attachment.name}>
                      {attachment.name}
                    </p>
                    <p className="text-[10px] text-muted-foreground">{fileSize(attachment.size)}</p>
                  </div>
                  <IconButton
                    label={`${labels.removeAttachment}: ${attachment.name}`}
                    disabled={busy}
                    onClick={() => onRemoveAttachment(attachment.id)}
                    size="sm"
                  >
                    <X size={14} aria-hidden="true" />
                  </IconButton>
                </div>
              ))}
            </div>
          ) : null}

          <AutoTextarea
            ref={inputRef}
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            aria-label={labels.input}
            aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`}
            aria-invalid={error ? true : undefined}
            placeholder={labels.placeholder}
            className="px-2 pt-2"
            onCompositionStart={() => {
              composing.current = true
            }}
            onCompositionEnd={() => {
              composing.current = false
            }}
            onKeyDown={(event) => {
              if (
                event.key !== 'Enter' ||
                event.shiftKey ||
                event.nativeEvent.isComposing ||
                composing.current ||
                event.keyCode === 229
              )
                return
              event.preventDefault()
              if (canSubmit && !event.repeat) onSubmit()
            }}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files)
              if (files.length > 0) {
                event.preventDefault()
                addFiles(files)
              }
            }}
          />
        </div>
        <div className="mt-2 flex min-w-0 items-center gap-1">
          <input
            ref={fileInputRef}
            type="file"
            accept={accept}
            multiple
            tabIndex={-1}
            aria-label={labels.addFiles}
            disabled={busy}
            className="hidden"
            onChange={(event) => {
              addFiles(Array.from(event.target.files ?? []))
              event.target.value = ''
            }}
          />
          <ComposerActionMenu
            label={labels.addContext ?? labels.addFiles}
            hint={labels.actionsHint}
            triggerRef={actionTriggerRef}
            disabled={busy}
            actions={[
              {
                id: 'composer-files',
                kind: 'action',
                label: labels.addFiles,
                description: labels.uploadDescription,
                icon: <Paperclip size={18} strokeWidth={1.7} />,
                onSelect: () => fileInputRef.current?.click(),
              },
              ...actions,
              ...tools.map((tool) => ({
                id: `composer-tool-${tool.id}`,
                kind: 'toggle' as const,
                label: tool.label,
                description: tool.description,
                icon: tool.icon ?? <SlidersHorizontal size={17} />,
                group: labels.tools,
                checked: tool.enabled,
                onCheckedChange: () => onToolToggle(tool.id),
              })),
            ]}
          />

          <div className="min-w-0 flex-1" />

          {models.length > 0 ? (
            <Menu>
              <MenuTrigger disabled={busy} aria-label={labels.model} className={`${triggerClassName} max-w-[45%]`}>
                <span className="truncate">{activeModel?.label ?? labels.model}</span>
                <ChevronDown size={13} aria-hidden="true" className="shrink-0" />
              </MenuTrigger>
              <MenuContent align="end" aria-label={labels.model}>
                <MenuRadioGroup value={modelId} onValueChange={(next: string) => onModelChange(next)}>
                  {models.map((model) => (
                    <MenuRadioItem key={model.id} value={model.id}>
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{model.label}</span>
                        {model.description ? (
                          <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{model.description}</span>
                        ) : null}
                      </span>
                      <span className="flex size-4 shrink-0 items-center justify-center">
                        {model.id === modelId ? <Check size={15} aria-hidden="true" /> : null}
                      </span>
                    </MenuRadioItem>
                  ))}
                </MenuRadioGroup>
              </MenuContent>
            </Menu>
          ) : null}

          {busy ? (
            <IconButton
              key="stop"
              label={labels.stop}
              tone="solid"
              onClick={(event) => {
                event.preventDefault()
                onStop()
              }}
            >
              <Square size={14} fill="currentColor" strokeWidth={0} aria-hidden="true" />
            </IconButton>
          ) : (
            <IconButton key="submit" label={labels.submit} type="submit" tone="solid" disabled={!canSubmit}>
              <ArrowUp size={20} strokeWidth={2} aria-hidden="true" />
            </IconButton>
          )}
        </div>

        {isDragging ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-3 rounded-panel border-2 border-dashed border-muted-foreground bg-card/95 text-sm text-foreground">
            <Upload size={20} aria-hidden="true" />
            {labels.dropFiles}
          </div>
        ) : null}
      </form>

      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-2 px-3 text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <p id={`${id}-hint`} className="sr-only">
        {labels.keyboardHint} {labels.attachmentHint}
      </p>
    </div>
  )
}
