import { describe, expect, it } from 'vitest'

import { en, zhCN } from '.'

function collectLeafKeys(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key

    return typeof child === 'object' && child !== null ? collectLeafKeys(child, path) : path
  })
}

describe('translation resources', () => {
  it('keeps the English and Chinese resource trees aligned', () => {
    expect(collectLeafKeys(zhCN).sort()).toEqual(collectLeafKeys(en).sort())
  })
})
