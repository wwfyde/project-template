import { Button as ButtonPrimitive } from '@base-ui/react/button'
import type { ComponentPropsWithRef } from 'react'

const variants = {
  ghost: 'text-foreground hover:bg-accent hover:text-accent-foreground',
  outline: 'border border-border bg-background text-foreground hover:bg-accent hover:text-accent-foreground',
  solid: 'bg-primary text-primary-foreground shadow-control hover:bg-primary-hover',
} as const

const sizes = {
  default: 'min-h-control px-3 py-2',
  icon: 'size-control p-0',
  'icon-sm': 'size-8 p-0',
  'icon-xs': 'size-7 p-0',
} as const

export type ButtonProps = Omit<ComponentPropsWithRef<typeof ButtonPrimitive>, 'className'> & {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
  className?: string
}

export function Button({
  variant = 'solid',
  size = 'default',
  className = '',
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <ButtonPrimitive
      {...props}
      type={type}
      data-slot="button"
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-control text-sm font-medium transition-colors duration-(--motion-duration) ease-(--motion-easing) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-disabled:pointer-events-none data-disabled:opacity-50 motion-reduce:transition-none ${variants[variant]} ${sizes[size]} ${className}`}
    />
  )
}
