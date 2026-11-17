import { Dialog as DialogPrimitive } from '@base-ui/react/dialog'
import { X } from 'lucide-react'
import { useId, type ReactNode, type RefObject } from 'react'

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  closeLabel,
  returnFocusRef,
  initialFocusRef,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  closeLabel: string
  returnFocusRef?: RefObject<HTMLElement | null>
  initialFocusRef?: RefObject<HTMLElement | null>
  children: ReactNode
}) {
  const titleId = useId()
  const descriptionId = useId()
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/30 transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <DialogPrimitive.Popup
          aria-labelledby={titleId}
          aria-describedby={description ? descriptionId : undefined}
          finalFocus={returnFocusRef}
          initialFocus={initialFocusRef}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-32px)] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[22px] border border-agent-border bg-agent-surface text-agent-text shadow-xl outline-none"
        >
          <div className="shrink-0 border-b border-agent-border px-5 py-5 pr-16 sm:px-6 sm:pr-16">
            <DialogPrimitive.Title id={titleId} className="text-lg font-semibold tracking-tight">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description id={descriptionId} className="mt-2 text-xs leading-5 text-agent-muted">
                {description}
              </DialogPrimitive.Description>
            ) : null}
            <DialogPrimitive.Close
              aria-label={closeLabel}
              className="absolute right-3 top-3 flex size-10 items-center justify-center rounded-full text-agent-muted hover:bg-agent-subtle focus-visible:outline-2 focus-visible:outline-agent-muted"
            >
              <X size={18} aria-hidden="true" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
