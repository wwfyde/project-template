import { Dialog } from '@base-ui/react/dialog'
import { X } from 'lucide-react'
import { useId, type ReactNode, type RefObject } from 'react'

export function Sheet({
  open,
  onOpenChange,
  title,
  closeLabel,
  children,
  returnFocusRef,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  closeLabel: string
  children: ReactNode
  returnFocusRef?: RefObject<HTMLElement | null>
}) {
  const titleId = useId()
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-overlay transition-opacity duration-(--motion-duration) ease-(--motion-easing) data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Popup
          aria-labelledby={titleId}
          finalFocus={returnFocusRef}
          className="fixed inset-y-0 left-0 z-50 w-[min(300px,85vw)] bg-sidebar text-sidebar-foreground shadow-panel backdrop-blur-surface outline-none"
        >
          <Dialog.Title id={titleId} className="sr-only">
            {title}
          </Dialog.Title>
          <Dialog.Close
            aria-label={closeLabel}
            className="absolute right-4 top-5 z-10 flex size-control items-center justify-center rounded-control hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          >
            <X size={18} aria-hidden="true" />
          </Dialog.Close>
          {children}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
