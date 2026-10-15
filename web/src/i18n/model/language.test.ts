import { describe, expect, it } from 'vitest'

import { resolveAppLanguage } from './language'

describe('resolveAppLanguage', () => {
  it.each([
    ['zh', 'zh-CN'],
    ['zh-CN', 'zh-CN'],
    ['zh-TW', 'zh-CN'],
    ['en', 'en'],
    ['en-US', 'en'],
    ['fr-FR', 'en'],
    [undefined, 'en'],
  ])('maps %s to %s', (input, expected) => {
    expect(resolveAppLanguage(input)).toBe(expected)
  })
})
