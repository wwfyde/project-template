import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import type { ComponentPropsWithRef, RefObject } from 'react'

export type AnchoredPopoverProps = Omit<
  ComponentPropsWithRef<typeof PopoverPrimitive.Popup>,
  'className' | 'role' | 'initialFocus' | 'finalFocus'
> & {
  open: boolean
  anchor: HTMLElement | RefObject<HTMLElement | null> | null
  side: 'left' | 'right'
  onOpenChange?: ComponentPropsWithRef<typeof PopoverPrimitive.Root>['onOpenChange']
  role?: 'dialog' | 'tooltip'
  className?: string
}

/** Positioned surface only; the caller owns hover, selection, and focus transfer. */
export function AnchoredPopover({
  open,
  anchor,
  side,
  onOpenChange,
  role = 'dialog',
  className = '',
  ...props
}: AnchoredPopoverProps) {
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange} modal={false}>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          anchor={anchor}
          side={side}
          align="center"
          sideOffset={12}
          collisionPadding={8}
          collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'end' }}
          className="z-50"
        >
          <PopoverPrimitive.Popup
            {...props}
            role={role}
            initialFocus={false}
            finalFocus={false}
            data-slot="anchored-popover"
            className={`max-h-[var(--available-height)] max-w-[min(28rem,var(--available-width),calc(100vw-1rem))] overflow-y-auto rounded-xl border border-border bg-popover p-4 text-sm text-popover-foreground shadow-lg outline-none [overflow-wrap:anywhere] ${className}`}
          />
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
