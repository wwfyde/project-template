import { useImperativeHandle, useLayoutEffect, useRef, type ComponentPropsWithRef } from 'react'

export type AutoTextareaProps = ComponentPropsWithRef<'textarea'>

export function AutoTextarea({ ref, value, className = '', ...props }: AutoTextareaProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => inputRef.current!)

  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = 'auto'
    input.style.height = `${Math.max(64, Math.min(input.scrollHeight, 200))}px`
  }, [value])

  return (
    <textarea
      {...props}
      ref={inputRef}
      value={value}
      rows={2}
      data-slot="auto-textarea"
      className={`block max-h-[200px] min-h-16 w-full resize-none border-0 bg-transparent text-base leading-7 text-agent-text outline-none placeholder:text-agent-muted ${className}`}
    />
  )
}
