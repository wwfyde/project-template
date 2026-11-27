import { Button, type ButtonProps } from './button'

const sizes = { default: 'icon', sm: 'icon-sm', xs: 'icon-xs' } as const

export type IconButtonProps = Omit<ButtonProps, 'variant' | 'size'> & {
  label: string
  tone?: 'ghost' | 'solid'
  size?: keyof typeof sizes
  className?: string
}

export function IconButton({
  label,
  tone = 'ghost',
  size = 'default',
  className = '',
  type = 'button',
  ...props
}: IconButtonProps) {
  return (
    <Button
      {...props}
      type={type}
      aria-label={label}
      title={label}
      variant={tone}
      size={sizes[size]}
      className={className}
    />
  )
}
