export const MESSAGE_BOOKMARK_STORAGE_PREFIX = 'project-template.user-message-bookmarks.v1:'

export type BookmarkStorage = Pick<Storage, 'getItem' | 'setItem'>

function browserStorage(): BookmarkStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function messageBookmarkStorageKey(conversationId: string): string {
  return `${MESSAGE_BOOKMARK_STORAGE_PREFIX}${encodeURIComponent(conversationId)}`
}

export function readMessageBookmarks(
  conversationId: string,
  storage: BookmarkStorage | null = browserStorage(),
): ReadonlySet<string> {
  try {
    const raw = storage?.getItem(messageBookmarkStorageKey(conversationId))
    if (!raw) return new Set()
    const value: unknown = JSON.parse(raw)
    if (
      !Array.isArray(value) ||
      !value.every((id): id is string => typeof id === 'string' && id.length > 0)
    ) {
      return new Set()
    }
    return new Set(value)
  } catch {
    return new Set()
  }
}

export function writeMessageBookmarks(
  conversationId: string,
  ids: ReadonlySet<string>,
  storage: BookmarkStorage | null = browserStorage(),
): void {
  try {
    storage?.setItem(messageBookmarkStorageKey(conversationId), JSON.stringify([...ids]))
  } catch {
    // An unavailable or full storage must not prevent using bookmarks in this session.
  }
}

/** Stable snapshots keep unsaved bookmarks available when switching between conversations. */
export function createMessageBookmarkStore(storage: BookmarkStorage | null = browserStorage()) {
  const snapshots = new Map<string, ReadonlySet<string>>()
  const listeners = new Set<() => void>()

  const get = (conversationId: string): ReadonlySet<string> => {
    let snapshot = snapshots.get(conversationId)
    if (!snapshot) {
      snapshot = readMessageBookmarks(conversationId, storage)
      snapshots.set(conversationId, snapshot)
    }
    return snapshot
  }

  return {
    get,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    set(conversationId: string, id: string, bookmarked: boolean) {
      if (!id) return
      const previous = get(conversationId)
      if (previous.has(id) === bookmarked) return
      const next = new Set(previous)
      if (bookmarked) next.add(id)
      else next.delete(id)
      snapshots.set(conversationId, next)
      writeMessageBookmarks(conversationId, next, storage)
      listeners.forEach((listener) => listener())
    },
  }
}
