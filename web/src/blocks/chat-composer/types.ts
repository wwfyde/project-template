import type { ReactNode, RefObject } from 'react'

export type ComposerAttachment = { id: string; name: string; size: number }
export type ComposerModel = { id: string; label: string; description?: string }
export type ComposerTool = { id: string; label: string; enabled: boolean; description?: string; icon?: ReactNode }

type ComposerActionBase = {
  id: string
  label: string
  description?: string
  icon?: ReactNode
  group?: string
  disabled?: boolean
  disabledReason?: string
}

export type ComposerAction = ComposerActionBase &
  (
    | { kind: 'action'; onSelect: () => void }
    | { kind: 'toggle'; checked: boolean; onCheckedChange: (checked: boolean) => void }
  )

export type ComposerSelection = { id: string; label: string; description?: string; icon?: ReactNode }

export type ComposerLabels = {
  input: string
  placeholder: string
  addFiles: string
  removeAttachment: string
  model: string
  tools: string
  submit: string
  stop: string
  dropFiles: string
  keyboardHint: string
  attachmentHint: string
  addContext?: string
  actionsHint?: string
  removeSelection?: string
  uploadDescription?: string
}

export type ChatComposerProps = {
  value: string
  onValueChange: (value: string) => void
  attachments: ComposerAttachment[]
  onFilesAdded: (files: File[]) => void
  onRemoveAttachment: (id: string) => void
  modelId: string
  models: ComposerModel[]
  onModelChange: (id: string) => void
  tools: ComposerTool[]
  onToolToggle: (id: string) => void
  actions?: ComposerAction[]
  selections?: ComposerSelection[]
  onRemoveSelection?: (id: string) => void
  /** The host decides whether selected references can be sent without text. Tools alone cannot. */
  hasContext?: boolean
  inputRef?: RefObject<HTMLTextAreaElement | null>
  actionTriggerRef?: RefObject<HTMLButtonElement | null>
  busy: boolean
  onSubmit: () => void
  onStop: () => void
  labels: ComposerLabels
  context?: ReactNode
  accept?: string
  error?: string
  className?: string
}
