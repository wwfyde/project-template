import { describe, expect, it, vi } from 'vitest'

import { createSkillClient, skillContentPath } from './skill-client'

describe('Skills API client', () => {
  it('uploads ZIP bytes with the official files field and leaves multipart headers to the browser', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({})
    const file = new File(['zip'], 'review.zip', { type: 'application/zip' })
    await createSkillClient({ authenticatedRequest }).create({ kind: 'zip', file })
    const [path, init] = authenticatedRequest.mock.calls[0]
    expect(path).toBe('/api/skills')
    expect(init.method).toBe('POST')
    expect(init.headers).toBeUndefined()
    expect(init.body.get('files')).toBe(file)
    expect(init.body.has('default')).toBe(false)
  })

  it('preserves relative directory paths instead of flattening identically named files', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({})
    const files = ['review/SKILL.md', 'review/references/notes.md', 'review/examples/notes.md'].map((path) => {
      const file = new File(['text'], path.split('/').at(-1)!)
      Object.defineProperty(file, 'webkitRelativePath', { value: path })
      return file
    })
    await createSkillClient({ authenticatedRequest }).createVersion('skill_1', { kind: 'directory', files }, true)
    const [path, init] = authenticatedRequest.mock.calls[0]
    expect(path).toBe('/api/skills/skill_1/versions')
    expect(init.body.getAll('files[]').map((file: File) => file.name)).toEqual([
      'review/SKILL.md',
      'review/references/notes.md',
      'review/examples/notes.md',
    ])
    expect(init.body.get('default')).toBe('true')
  })

  it('encodes IDs, versions, file paths and cursor values without changing the endpoint', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({})
    const client = createSkillClient({ authenticatedRequest })
    await client.file('a/b', 'references/a?x=1&y=#.md', '2/3')
    expect(authenticatedRequest.mock.calls[0][0]).toBe(
      '/api/skills/a%2Fb/versions/2%2F3/files?path=references%2Fa%3Fx%3D1%26y%3D%23.md',
    )
    await client.versions('a/b', { after: 'v/?&', order: 'asc', limit: 0 })
    expect(authenticatedRequest.mock.calls[1][0]).toBe('/api/skills/a%2Fb/versions?limit=0&order=asc&after=v%2F%3F%26')
    expect(skillContentPath('a/b', '1')).toBe('/api/skills/a%2Fb/versions/1/content')
    expect(skillContentPath('a/b')).toBe('/api/skills/a%2Fb/content')
  })

  it('delegates authentication and cancellation and changes default using POST JSON', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({})
    const client = createSkillClient({ authenticatedRequest })
    const controller = new AbortController()
    await client.tree('skill_1', 'latest', controller.signal)
    expect(authenticatedRequest).toHaveBeenLastCalledWith('/api/skills/skill_1/versions/latest/tree', {
      signal: controller.signal,
    })
    await client.setDefault('skill_1', '2')
    expect(authenticatedRequest).toHaveBeenLastCalledWith('/api/skills/skill_1', {
      method: 'POST',
      body: '{"default_version":"2"}',
    })
    await client.deleteVersion('skill_1', '2')
    expect(authenticatedRequest).toHaveBeenLastCalledWith('/api/skills/skill_1/versions/2', { method: 'DELETE' })
  })
})
