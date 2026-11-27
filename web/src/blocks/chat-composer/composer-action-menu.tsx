import { Check, Plus } from 'lucide-react'
import { Fragment, type RefObject } from 'react'

import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from '../../components/ui/menu'
import type { ComposerAction } from './types'

export function ComposerActionMenu({
  actions,
  label,
  hint,
  disabled = false,
  triggerRef,
}: {
  actions: ComposerAction[]
  label: string
  hint?: string
  disabled?: boolean
  triggerRef?: RefObject<HTMLButtonElement | null>
}) {
  const groups = new Map<string, ComposerAction[]>()
  for (const action of actions) {
    const name = action.group ?? ''
    const items = groups.get(name) ?? []
    items.push(action)
    groups.set(name, items)
  }

  return (
    <Menu>
      <MenuTrigger
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-label={label}
        title={label}
        className="inline-flex size-control shrink-0 items-center justify-center rounded-control text-foreground transition-colors duration-(--motion-duration) ease-(--motion-easing) hover:bg-accent data-popup-open:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring data-disabled:cursor-not-allowed data-disabled:opacity-35"
      >
        <Plus size={21} strokeWidth={1.7} aria-hidden="true" />
      </MenuTrigger>
      <MenuContent size="composer" aria-label={label}>
        {[...groups].map(([name, items], index) => (
          <Fragment key={name}>
            {index > 0 ? <MenuSeparator /> : null}
            <MenuGroup>
              {name ? <MenuGroupLabel>{name}</MenuGroupLabel> : null}
              {items.map((action) => {
                const description = action.disabledReason ?? action.description
                const content = (
                  <>
                    <span
                      className="flex size-6 shrink-0 items-center justify-center text-muted-foreground"
                      aria-hidden="true"
                    >
                      {action.icon ?? <Plus size={17} />}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                      <span className="shrink-0 text-[13px] font-medium">{action.label}</span>
                      {description ? (
                        <span className="min-w-0 text-xs leading-5 text-muted-foreground sm:truncate" title={description}>
                          {description}
                        </span>
                      ) : null}
                    </span>
                    {action.kind === 'toggle' ? (
                      <span className="flex size-4 shrink-0 items-center justify-center">
                        {action.checked ? <Check size={15} aria-hidden="true" /> : null}
                      </span>
                    ) : null}
                  </>
                )
                return action.kind === 'toggle' ? (
                  <MenuCheckboxItem
                    key={action.id}
                    label={action.label}
                    disabled={disabled || action.disabled}
                    checked={action.checked}
                    onCheckedChange={action.onCheckedChange}
                    closeOnClick
                  >
                    {content}
                  </MenuCheckboxItem>
                ) : (
                  <MenuItem
                    key={action.id}
                    label={action.label}
                    disabled={disabled || action.disabled}
                    onClick={() => action.onSelect()}
                  >
                    {content}
                  </MenuItem>
                )
              })}
            </MenuGroup>
          </Fragment>
        ))}
        {hint ? (
          <p className="mx-2 mt-1.5 border-t border-border px-1 pb-1.5 pt-2 text-[10px] leading-4 text-muted-foreground">
            {hint}
          </p>
        ) : null}
      </MenuContent>
    </Menu>
  )
}
