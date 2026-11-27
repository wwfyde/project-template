import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import type { ReactNode } from 'react'

export type SegmentedTabOption<Value extends string> = {
  value: Value
  label: string
  icon?: ReactNode
}

export type SegmentedTabsProps<Value extends string> = {
  value: Value
  onValueChange: (value: Value) => void
  options: SegmentedTabOption<Value>[]
  label: string
  className?: string
  panelId?: string
}

export function SegmentedTabs<Value extends string>({
  value,
  onValueChange,
  options,
  label,
  className = '',
  panelId,
}: SegmentedTabsProps<Value>) {
  return (
    <TabsPrimitive.Root
      value={value}
      onValueChange={(next) => {
        const option = options.find((candidate) => candidate.value === next)
        if (option) onValueChange(option.value)
      }}
      className={`inline-flex ${className}`}
    >
      <TabsPrimitive.List
        activateOnFocus
        aria-label={label}
        className="inline-flex gap-1 rounded-control bg-muted p-1"
      >
        {options.map((option) => (
          <TabsPrimitive.Tab
            key={option.value}
            value={option.value}
            id={panelId ? `${panelId}-tab-${option.value}` : undefined}
            aria-controls={panelId}
            className="inline-flex min-h-control items-center justify-center gap-2 rounded-control px-5 text-sm font-medium text-muted-foreground transition-colors duration-(--motion-duration) ease-(--motion-easing) hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring data-active:bg-card data-active:text-foreground data-active:shadow-control motion-reduce:transition-none"
          >
            {option.icon}
            {option.label}
          </TabsPrimitive.Tab>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  )
}
