import { describe, expect, it } from 'vitest'

import { normalizeReturnTo } from './return-to'

const origin = 'https://app.example.test'

describe('normalizeReturnTo', () => {
  it.each([
    ['/assets?tab=shared#recent', '/assets?tab=shared#recent'],
    [`${origin}/admin/dashboard`, '/admin/dashboard'],
    ['/about?next=https://example.test', '/about?next=https://example.test'],
  ])('preserves local application locations: %s', (input, expected) => {
    expect(normalizeReturnTo(input, origin)).toBe(expected)
  })

  it.each([
    undefined,
    '',
    'https://attacker.example/path',
    '//attacker.example/path',
    '/\\attacker.example/path',
    '/%2f%2fattacker.example/path',
    '/%5cattacker.example/path',
    'javascript:alert(1)',
    'https://name:password@app.example.test/about',
    '/login?redirect=/login',
    '/api/auth/logout',
    '/assets/../api/auth/oauth/google/callback',
    '/%61pi/auth/session',
    '/broken%ZZ',
    '/path\nwith-control',
  ])('rejects unsafe redirects and authentication loops: %s', (input) => {
    expect(normalizeReturnTo(input, origin)).toBe('/')
  })
})
