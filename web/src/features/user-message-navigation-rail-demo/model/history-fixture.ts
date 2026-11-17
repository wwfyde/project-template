import type { UserMessagePreview } from '../../../blocks/user-message-navigation-rail'
import type { ConversationDemoLanguage, ConversationDemoTurn } from './conversation'

export const HIDDEN_HISTORY_COUNT = 8

export function fixturePreview(
  turn: ConversationDemoTurn,
  index: number,
  language: ConversationDemoLanguage,
): UserMessagePreview {
  const chinese = language === 'zh-CN'
  const outputs =
    index === 5 || index === 18
      ? [
          {
            id: `${turn.id}-brief`,
            type: 'file' as const,
            label: chinese ? '示例：项目简报.md' : 'Demo: workspace-brief.md',
          },
          {
            id: `${turn.id}-screen`,
            type: 'image' as const,
            label: chinese ? '示例：页面草图' : 'Demo: screen sketch',
          },
          {
            id: `${turn.id}-review`,
            type: 'review' as const,
            label: chinese ? '示例：评审记录' : 'Demo: design review',
          },
        ]
      : undefined
  return { response: turn.answer, outputs }
}

export function waitForFixture(milliseconds: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false)
  return new Promise((resolve) => {
    const finish = () => {
      signal.removeEventListener('abort', cancel)
      resolve(true)
    }
    const timer = setTimeout(finish, milliseconds)
    const cancel = () => {
      clearTimeout(timer)
      resolve(false)
    }
    signal.addEventListener('abort', cancel, { once: true })
  })
}
