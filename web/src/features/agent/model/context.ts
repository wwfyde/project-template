export type ContextReference =
  | { id: string; kind: 'link'; title: string; url: string }
  | { id: string; kind: 'text'; title: string; text: string }
  | { id: string; kind: 'skill'; title: string; skillId: string; version: string; description: string }

export type ContextValidationError =
  | 'invalid-id'
  | 'invalid-title'
  | 'invalid-url'
  | 'empty-text'
  | 'text-too-long'
  | 'invalid-skill'
  | 'invalid-kind'

export const MAX_CONTEXTS = 8
export const MAX_CONTEXT_TEXT_LENGTH = 12_000
export const MAX_CONTEXT_TITLE_LENGTH = 80
export const MAX_CONTEXT_URL_LENGTH = 2_048

const controlCharacters = /\p{Cc}/u

/** Keep fragment identifiers: they can name a specific section of a source. */
export function normalizeContextUrl(input: string): string | null {
  if (typeof input !== 'string' || controlCharacters.test(input)) return null
  const candidate = input.trim()
  if (!candidate || candidate.length > MAX_CONTEXT_URL_LENGTH || /\s/u.test(candidate)) return null
  if (!/^https?:\/\//i.test(candidate)) return null
  try {
    const url = new URL(candidate)
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null
    return url.href.length <= MAX_CONTEXT_URL_LENGTH ? url.href : null
  } catch {
    return null
  }
}

/** Identity of a source, independent of the chip's generated identifier. */
export function contextKey(context: ContextReference): string {
  switch (context.kind) {
    case 'link':
      return JSON.stringify(['link', normalizeContextUrl(context.url) ?? context.url])
    case 'skill':
      return JSON.stringify(['skill', context.skillId.trim(), context.version.trim()])
    case 'text':
      return JSON.stringify(['text', context.id])
  }
}

export function validateContext(context: ContextReference): ContextValidationError | null {
  if (!context || typeof context.id !== 'string' || !context.id.trim() || controlCharacters.test(context.id)) {
    return 'invalid-id'
  }
  if (
    typeof context.title !== 'string' ||
    !context.title.trim() ||
    context.title.trim().length > MAX_CONTEXT_TITLE_LENGTH ||
    controlCharacters.test(context.title)
  ) {
    return 'invalid-title'
  }
  switch (context.kind) {
    case 'link':
      return normalizeContextUrl(context.url) ? null : 'invalid-url'
    case 'text':
      if (typeof context.text !== 'string' || !context.text.trim()) return 'empty-text'
      return context.text.length > MAX_CONTEXT_TEXT_LENGTH ? 'text-too-long' : null
    case 'skill':
      return typeof context.skillId === 'string' &&
        context.skillId.trim() &&
        !controlCharacters.test(context.skillId) &&
        typeof context.version === 'string' &&
        context.version.trim() &&
        !controlCharacters.test(context.version) &&
        typeof context.description === 'string' &&
        context.description.length <= MAX_CONTEXT_TEXT_LENGTH
        ? null
        : 'invalid-skill'
    default:
      return 'invalid-kind'
  }
}
