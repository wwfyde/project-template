import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import type { ComponentPropsWithRef } from 'react'

export const Menu = MenuPrimitive.Root
export const MenuTrigger = MenuPrimitive.Trigger
export const MenuRadioGroup = MenuPrimitive.RadioGroup
export const MenuGroup = MenuPrimitive.Group

export type MenuContentProps = Omit<ComponentPropsWithRef<typeof MenuPrimitive.Popup>, 'className'> &
  Pick<ComponentPropsWithRef<typeof MenuPrimitive.Positioner>, 'side' | 'align'> & {
    className?: string
    size?: 'default' | 'composer'
  }

export function MenuContent({
  side = 'top',
  align = 'start',
  size = 'default',
  className = '',
  ...props
}: MenuContentProps) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Positioner side={side} align={align} sideOffset={8} collisionPadding={12} className="z-50">
        <MenuPrimitive.Popup
          {...props}
          className={`${size === 'composer' ? 'max-h-[min(480px,var(--available-height))] w-[min(480px,calc(100vw-24px))] max-w-[var(--available-width)]' : 'max-h-[min(360px,var(--available-height))] min-w-52 max-w-[min(320px,calc(100vw-24px))]'} overflow-y-auto rounded-[14px] border border-agent-border bg-agent-surface p-1.5 text-agent-text shadow-lg outline-none transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0 motion-reduce:transition-none ${className}`}
        />
      </MenuPrimitive.Positioner>
    </MenuPrimitive.Portal>
  )
}

const itemClassName =
  'flex min-h-11 cursor-default items-center gap-3 rounded-[9px] px-3 py-2 text-sm outline-none data-highlighted:bg-agent-subtle data-disabled:opacity-40'

export function MenuItem({
  className = '',
  ...props
}: Omit<ComponentPropsWithRef<typeof MenuPrimitive.Item>, 'className'> & { className?: string }) {
  return <MenuPrimitive.Item {...props} className={`${itemClassName} ${className}`} />
}

export function MenuSeparator() {
  return <MenuPrimitive.Separator className="mx-2 my-1.5 h-px bg-agent-border" />
}

export function MenuGroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <MenuPrimitive.GroupLabel className="px-3 pb-1 pt-2 text-[10px] font-medium tracking-wide text-agent-muted">
      {children}
    </MenuPrimitive.GroupLabel>
  )
}

export function MenuRadioItem({
  className = '',
  ...props
}: Omit<ComponentPropsWithRef<typeof MenuPrimitive.RadioItem>, 'className'> & { className?: string }) {
  return <MenuPrimitive.RadioItem {...props} closeOnClick className={`${itemClassName} ${className}`} />
}

export function MenuCheckboxItem({
  className = '',
  ...props
}: Omit<ComponentPropsWithRef<typeof MenuPrimitive.CheckboxItem>, 'className'> & { className?: string }) {
  return <MenuPrimitive.CheckboxItem {...props} className={`${itemClassName} ${className}`} />
}
