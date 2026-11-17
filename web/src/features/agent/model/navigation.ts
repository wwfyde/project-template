import type { UserMessageNavigationItem } from '../../../blocks/user-message-navigation-rail'
import type { Message } from './workspace'

/** Pair each user message with assistant text before the next user message. */
export function userMessageNavigationItems(
  messages: readonly Message[],
  bookmarkedIds: ReadonlySet<string>,
): UserMessageNavigationItem[] {
  return messages.flatMap((message, index) => {
    if (message.role !== 'user') return []
    const responses: Message[] = []
    for (
      let next = index + 1;
      next < messages.length && messages[next].role !== 'user';
      next += 1
    ) {
      if (messages[next].role === 'assistant') responses.push(messages[next])
    }
    return [
      {
        id: message.id,
        turnKey: message.id,
        bookmarkId: message.id,
        getLabel: () => message.content,
        getPreview: () => ({
          response: responses
            .map((response) => response.content)
            .filter(Boolean)
            .join('\n\n'),
        }),
        isLoaded: true,
        isBookmarked: bookmarkedIds.has(message.id),
        previewState: 'loaded' as const,
      },
    ]
  })
}
