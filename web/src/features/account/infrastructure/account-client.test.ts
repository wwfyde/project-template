import { afterEach, describe, expect, it, vi } from 'vitest'

import { createAccountClient, validateAuthorizationUrl } from './account-client'
import { parseAccountSearch } from '../model/account'

afterEach(() => vi.unstubAllGlobals())

describe('account authorization', () => {
  it.each([
    ['google', 'https://accounts.google.com/o/oauth2/v2/auth?state=secure'],
    ['dingtalk', 'https://login.dingtalk.com/oauth2/auth?state=secure'],
  ])('allows the registered %s endpoint', (provider, url) => {
    expect(validateAuthorizationUrl(provider, url)).toBe(url)
  })

  it.each([
    ['google', 'http://accounts.google.com/o/oauth2/v2/auth'],
    ['google', 'https://accounts.google.com.attacker.example/o/oauth2/v2/auth'],
    ['google', 'https://accounts.google.com/redirect'],
    ['google', 'https://user@accounts.google.com/o/oauth2/v2/auth'],
    ['google', 'https://accounts.google.com/o/oauth2/v2/auth#token'],
    ['dingtalk', 'https://accounts.google.com/o/oauth2/v2/auth'],
    ['unknown', 'https://attacker.example'],
    ['google', 'javascript:alert(1)'],
    ['google', '//accounts.google.com/o/oauth2/v2/auth'],
  ])('rejects an unexpected provider destination: %s %s', (provider, url) => {
    expect(() => validateAuthorizationUrl(provider, url)).toThrow()
  })

  it('starts binding and verification through separate authenticated POST endpoints', async () => {
    const assign = vi.fn()
    vi.stubGlobal('window', { location: { assign } })
    const authenticatedRequest = vi
      .fn()
      .mockResolvedValue({ authorization_url: 'https://login.dingtalk.com/oauth2/auth?state=secure' })
    const client = createAccountClient({ authenticatedRequest })
    await client.startOAuth('dingtalk')
    await client.startOAuth('dingtalk', true)
    expect(authenticatedRequest.mock.calls).toEqual([
      ['/api/account/identities/dingtalk/start', { method: 'POST' }],
      ['/api/account/reauth/oauth/dingtalk/start', { method: 'POST' }],
    ])
    expect(assign).toHaveBeenCalledTimes(2)
    await expect(client.startOAuth('unknown')).rejects.toThrow('unavailable')
    expect(authenticatedRequest).toHaveBeenCalledTimes(2)
  })

  it('does not navigate to a malformed API authorization response', async () => {
    const assign = vi.fn()
    vi.stubGlobal('window', { location: { assign } })
    const client = createAccountClient({
      authenticatedRequest: vi.fn().mockResolvedValue({ authorization_url: 'https://attacker.example' }),
    })
    await expect(client.startOAuth('google')).rejects.toThrow('Invalid')
    expect(assign).not.toHaveBeenCalled()
  })

  it('keeps identity IDs confined to one route segment and sends password fields only in the body', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({ requires_login: false })
    const client = createAccountClient({ authenticatedRequest })
    await client.unlink('user/identity?provider=google')
    await client.setPassword({ username: 'example', password: 'a-private-password' })
    await client.reauthenticatePassword('a-private-password')
    expect(authenticatedRequest.mock.calls).toEqual([
      ['/api/account/identities/user%2Fidentity%3Fprovider%3Dgoogle', { method: 'DELETE' }],
      [
        '/api/account/password',
        { method: 'PUT', body: JSON.stringify({ username: 'example', password: 'a-private-password' }) },
      ],
      ['/api/account/reauth/password', { method: 'POST', body: JSON.stringify({ password: 'a-private-password' }) }],
    ])
  })

  it('accepts only known callback messages and never renders arbitrary query content', () => {
    expect(parseAccountSearch({ account_action: 'linked', account_error: 'identity_conflict' })).toEqual({
      account_action: 'linked',
      account_error: 'identity_conflict',
    })
    expect(parseAccountSearch({ account_action: '<script>', account_error: 'attacker supplied content' })).toEqual({
      account_action: undefined,
      account_error: 'request_failed',
    })
    expect(parseAccountSearch({ account_error: ['identity_conflict'] })).toEqual({
      account_action: undefined,
      account_error: undefined,
    })
  })
})
