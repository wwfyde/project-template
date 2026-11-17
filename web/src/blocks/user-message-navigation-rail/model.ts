export type UserMessageOutput = {
  id: string
  label: string
  type?:
    | 'app'
    | 'commit'
    | 'file'
    | 'google-drive'
    | 'image'
    | 'pull-request'
    | 'review'
    | 'website'
}

export type UserMessagePreview = {
  response?: string
  outputs?: readonly UserMessageOutput[]
}

export type UserMessagePreviewState = 'loading' | 'loaded' | 'unavailable'

/** One item per user message. Getters allow streaming content to remain live. */
export type UserMessageNavigationItem = {
  id: string
  turnKey?: string
  bookmarkId?: string
  getLabel: () => string
  getPreview?: () => UserMessagePreview | undefined
  isLoaded?: boolean
  isBookmarked?: boolean
  previewState?: UserMessagePreviewState
}

export type UserMessageNavigationSource = 'click' | 'keyboard' | 'shortcut' | 'scrub'
export type UserMessageNavigationOptions = {
  source: UserMessageNavigationSource
  behavior: 'smooth' | 'instant'
  signal: AbortSignal
}
export type UserMessagePreviewLoader = (
  item: UserMessageNavigationItem,
  options: { signal: AbortSignal },
) => Promise<UserMessagePreview | null>

export const MIN_NAVIGATION_ITEMS = 4
export const MIN_RAIL_SPACE = 48
export const PREVIEW_DELAY = 150

/** Match the compact piano markers: 6→26px with three neighboring levels. */
export function markerProgress(index: number, selectedIndex: number | null): number {
  if (selectedIndex === null) return 0
  return [1, 0.7, 0.4, 0.2][Math.abs(index - selectedIndex)] ?? 0
}

export function keyboardIndex(key: string, index: number, count: number): number | null {
  if (!count) return null
  switch (key) {
    case 'ArrowUp':
      return Math.max(0, index - 1)
    case 'ArrowDown':
      return Math.min(count - 1, index + 1)
    case 'Home':
      return 0
    case 'End':
      return count - 1
    default:
      return null
  }
}

export function scrollBehavior(
  distance: number,
  viewportHeight: number,
  reducedMotion: boolean,
  source: UserMessageNavigationSource,
): 'smooth' | 'instant' {
  return reducedMotion || source === 'scrub' || Math.abs(distance) > viewportHeight
    ? 'instant'
    : 'smooth'
}
