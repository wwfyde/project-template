import { describe, expect, it } from 'vitest'

import { userMessageNavigationItems } from './navigation'
import type { Message } from './workspace'

const message = (id: string, role: Message['role'], content: string): Message => ({
  id,
  role,
  content,
  status: 'completed',
})

describe('userMessageNavigationItems', () => {
  it('indexes only user messages and groups responses until the next question', () => {
    const items = userMessageNavigationItems(
      [
        message('intro', 'assistant', 'Intro'),
        message('q1', 'user', 'First question'),
        message('a1', 'assistant', 'First part'),
        message('a2', 'assistant', 'Second part'),
        message('q2', 'user', 'Next question'),
        message('a3', 'assistant', 'Next answer'),
      ],
      new Set(['q2']),
    )

    expect(items.map((item) => item.id)).toEqual(['q1', 'q2'])
    expect(items[0].getLabel()).toBe('First question')
    expect(items[0].getPreview?.()?.response).toBe('First part\n\nSecond part')
    expect(items[1].getPreview?.()?.response).toBe('Next answer')
    expect(items[1].isBookmarked).toBe(true)
  })

  it('does not present user attachments as generated outputs', () => {
    const items = userMessageNavigationItems(
      [
        {
          ...message('q', 'user', 'Review this'),
          attachments: [{ id: 'input', name: 'input.pdf', size: 20 }],
        },
        message('a', 'assistant', 'Here is a response'),
      ],
      new Set(),
    )

    expect(items[0].getPreview?.()?.outputs).toBeUndefined()
  })
})
