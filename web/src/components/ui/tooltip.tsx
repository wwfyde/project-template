import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip'
import type { ComponentPropsWithRef } from 'react'

export const Tooltip = TooltipPrimitive.Root
export const TooltipTrigger = TooltipPrimitive.Trigger

export type TooltipContentProps = Omit<ComponentPropsWithRef<typeof TooltipPrimitive.Popup>, 'className'> &
  Pick<ComponentPropsWithRef<typeof TooltipPrimitive.Positioner>, 'side' | 'align' | 'sideOffset'> & {
    className?: string
  }

// Keep tooltip content descriptive; interactive controls belong in a popover.
export function TooltipContent({
  side = 'top',
  align = 'center',
  sideOffset = 6,
  className = '',
  ...props
}: TooltipContentProps) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Positioner
        side={side}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={8}
        collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'end' }}
        className="z-50"
      >
        <TooltipPrimitive.Popup
          role="tooltip"
          {...props}
          data-slot="tooltip-content"
          className={`max-w-[min(22rem,var(--available-width),calc(100vw-1rem))] rounded-lg border border-border bg-popover px-3 py-2 text-sm leading-relaxed text-popover-foreground shadow-lg outline-none [overflow-wrap:anywhere] transition-opacity duration-100 data-starting-style:opacity-0 data-ending-style:opacity-0 motion-reduce:transition-none ${className}`}
        />
      </TooltipPrimitive.Positioner>
    </TooltipPrimitive.Portal>
  )
}
