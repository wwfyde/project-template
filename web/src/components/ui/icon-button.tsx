import { Button as ButtonPrimitive } from '@base-ui/react/button'
import type { ComponentPropsWithRef } from 'react'

export type IconButtonProps = Omit<ComponentPropsWithRef<typeof ButtonPrimitive>, 'className'> & {
  label: string
  tone?: 'ghost' | 'solid'
  className?: string
}

export function IconButton({ label, tone = 'ghost', className = '', type = 'button', ...props }: IconButtonProps) {
  return (
    <ButtonPrimitive
      {...props}
      type={type}
      aria-label={label}
      title={label}
      data-slot="icon-button"
      className={`inline-flex size-10 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-agent-muted data-disabled:cursor-not-allowed data-disabled:opacity-35 motion-reduce:transition-none ${tone === 'solid' ? 'bg-agent-strong text-agent-on-strong hover:opacity-85' : 'text-agent-text hover:bg-agent-subtle'} ${className}`}
    />
  )
}
