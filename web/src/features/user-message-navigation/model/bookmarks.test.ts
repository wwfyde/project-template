import { describe, expect, it, vi } from 'vitest'

import {
  createMessageBookmarkStore,
  messageBookmarkStorageKey,
  readMessageBookmarks,
  writeMessageBookmarks,
  type BookmarkStorage,
} from './bookmarks'

function memoryStorage(): BookmarkStorage {
  const values = new Map<string, string>()
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value)
    }),
  }
}

describe('message bookmark persistence', () => {
  it('isolates conversations and safely encodes their storage keys', () => {
    const storage = memoryStorage()
    const store = createMessageBookmarkStore(storage)
    store.set('workspace/one', 'shared-message-id', true)
    store.set('workspace/two', 'second-message', true)

    expect(messageBookmarkStorageKey('workspace/one')).toBe(
      'project-template.user-message-bookmarks.v1:workspace%2Fone',
    )
    expect([...store.get('workspace/one')]).toEqual(['shared-message-id'])
    expect([...store.get('workspace/two')]).toEqual(['second-message'])
    expect([...readMessageBookmarks('workspace/one', storage)]).toEqual(['shared-message-id'])
    expect([...readMessageBookmarks('workspace/two', storage)]).toEqual(['second-message'])
    expect(storage.setItem).toHaveBeenCalledTimes(2)
  })

  it('loads and deduplicates valid stored IDs without writing while reading or switching', () => {
    const storage = memoryStorage()
    storage.setItem(messageBookmarkStorageKey('one'), '["a","a","b"]')
    storage.setItem(messageBookmarkStorageKey('two'), '["c"]')
    vi.mocked(storage.setItem).mockClear()
    const store = createMessageBookmarkStore(storage)
    const first = store.get('one')

    expect([...first]).toEqual(['a', 'b'])
    expect([...store.get('two')]).toEqual(['c'])
    expect(store.get('one')).toBe(first)
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it.each(['broken json', '{}', 'null', '[1]', '["valid",false]', '[""]'])(
    'ignores invalid saved data: %s',
    (raw) => {
      const storage = memoryStorage()
      storage.setItem(messageBookmarkStorageKey('one'), raw)
      expect([...readMessageBookmarks('one', storage)]).toEqual([])
    },
  )

  it('retains per-conversation in-memory bookmarks when storage access fails', () => {
    const storage: BookmarkStorage = {
      getItem: () => {
        throw new Error('Access denied')
      },
      setItem: () => {
        throw new Error('Quota exceeded')
      },
    }
    const store = createMessageBookmarkStore(storage)
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)

    expect(() => store.set('one', 'message', true)).not.toThrow()
    expect([...store.get('two')]).toEqual([])
    expect([...store.get('one')]).toEqual(['message'])
    store.set('two', 'other', true)
    store.set('one', 'message', false)
    expect([...store.get('one')]).toEqual([])
    expect([...store.get('two')]).toEqual(['other'])
    expect(listener).toHaveBeenCalledTimes(3)

    unsubscribe()
    store.set('one', 'next', true)
    expect(listener).toHaveBeenCalledTimes(3)
  })

  it('does not write or notify for unchanged bookmark state', () => {
    const storage = memoryStorage()
    const store = createMessageBookmarkStore(storage)
    const listener = vi.fn()
    store.subscribe(listener)

    store.set('one', 'message', false)
    store.set('one', 'message', true)
    const saved = store.get('one')
    store.set('one', 'message', true)
    store.set('one', '', true)

    expect(store.get('one')).toBe(saved)
    expect(storage.setItem).toHaveBeenCalledTimes(1)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('supports sessions with no browser storage', () => {
    const store = createMessageBookmarkStore(null)
    store.set('one', 'message', true)

    expect([...store.get('one')]).toEqual(['message'])
    expect([...readMessageBookmarks('one', null)]).toEqual([])
    expect(() => writeMessageBookmarks('one', new Set(['message']), null)).not.toThrow()
  })
})
