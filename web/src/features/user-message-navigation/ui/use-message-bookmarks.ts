import { useCallback, useState, useSyncExternalStore } from 'react'

import { createMessageBookmarkStore } from '../model/bookmarks'

export function useMessageBookmarks(conversationId: string): {
  bookmarkedIds: ReadonlySet<string>
  setBookmarked: (id: string, bookmarked: boolean) => void
} {
  const [store] = useState(createMessageBookmarkStore)
  const getSnapshot = useCallback(() => store.get(conversationId), [conversationId, store])
  const bookmarkedIds = useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot)
  const setBookmarked = useCallback(
    (id: string, bookmarked: boolean) => store.set(conversationId, id, bookmarked),
    [conversationId, store],
  )

  return { bookmarkedIds, setBookmarked }
}
