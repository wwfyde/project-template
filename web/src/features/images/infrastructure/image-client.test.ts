import { describe, expect, it, vi } from 'vitest'

import { createImageClient, imageContentPath } from './image-client'
import { appendRevision, availableProviders, normalizePoint, type ImageAsset, type ImageProvider } from '../model/image'

describe('image editing client', () => {
  it('preserves browser multipart encoding and delegates credentials to authenticatedRequest', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({ id: 'asset' })
    const file = new File(['image'], 'source.png', { type: 'image/png' })
    await createImageClient({ authenticatedRequest }).upload(file)
    const [path, init] = authenticatedRequest.mock.calls[0]
    expect(path).toBe('/api/images/assets')
    expect(init.body.get('file')).toBe(file)
    expect(init.headers).toBeUndefined()
  })

  it('confines IDs to a path segment and submits edit choices in JSON', async () => {
    const authenticatedRequest = vi.fn().mockResolvedValue({})
    const edit = { operation: 'erase', provider: 'gemini', model: 'configured-model', mask_asset_id: 'mask' } as const
    await createImageClient({ authenticatedRequest }).edit('one/two?key=secret', edit)
    expect(authenticatedRequest).toHaveBeenCalledWith('/api/images/assets/one%2Ftwo%3Fkey%3Dsecret/edits', {
      method: 'POST',
      body: JSON.stringify(edit),
    })
    expect(imageContentPath('https://outside.example/image')).toBe(
      '/api/images/assets/https%3A%2F%2Foutside.example%2Fimage/content',
    )
  })

  it('keeps drag coordinates in the image even when pointer capture leaves its bounds', () => {
    const bounds = { left: 50, top: 100, width: 400, height: 200 }
    expect(normalizePoint(250, 150, bounds)).toEqual({ x: 0.5, y: 0.25 })
    expect(normalizePoint(-1, 400, bounds)).toEqual({ x: 0, y: 1 })
  })

  it('does not offer unconfigured providers or unsupported background removal', () => {
    const providers: ImageProvider[] = [
      {
        id: 'gpt',
        label: 'GPT',
        configured: false,
        operations: ['erase', 'remove_background'],
        models: [],
        default_model: null,
        mask_mode: 'native',
      },
      {
        id: 'gemini',
        label: 'Gemini',
        configured: true,
        operations: ['erase'],
        models: ['gemini-image'],
        default_model: 'gemini-image',
        mask_mode: 'reference',
      },
    ]
    expect(availableProviders(providers, 'remove_background')).toEqual([])
    expect(availableProviders(providers, 'erase').map((p) => p.id)).toEqual(['gemini'])
  })

  it('branches revision history after undo without mutating previous assets', () => {
    const original = { id: 'original' } as ImageAsset
    const oldEdit = { id: 'old' } as ImageAsset
    const newEdit = { id: 'new' } as ImageAsset
    const history = [original, oldEdit]
    expect(appendRevision(history, 0, newEdit)).toEqual([original, newEdit])
    expect(history).toEqual([original, oldEdit])
  })
})
