export type ImageOperation = 'markup' | 'remove_background' | 'erase' | 'resize'
export type ImageProviderId = 'local' | 'gpt' | 'gemini' | 'seedream' | 'veimagex'

export type ImageProvider = {
  id: ImageProviderId
  label: string
  configured: boolean
  models: string[]
  default_model: string | null
  operations: ImageOperation[]
  mask_mode: 'native' | 'reference' | null
  unavailable_reason?: string | null
}

export type ImageAsset = {
  id: string
  filename: string
  width: number
  height: number
  mime_type: string
  parent_id: string | null
  operation: string | null
  created_at: string
  content_url: string
}

export type Point = { x: number; y: number }
export type Markup = {
  kind: 'path' | 'text' | 'rectangle' | 'ellipse'
  points: Point[]
  color: string
  width: number
  text?: string
}

export type ImageEdit = {
  operation: ImageOperation
  provider?: ImageProviderId
  model?: string
  mask_asset_id?: string
  width?: number
  height?: number
  fit?: 'contain' | 'cover' | 'stretch'
  background?: string
  markup?: Markup[]
  prompt?: string
}

export type ImageComment = {
  id: string
  asset_id: string
  text: string
  x: number
  y: number
  created_at: string
}

export function normalizePoint(
  clientX: number,
  clientY: number,
  bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
): Point {
  return {
    x: Math.max(0, Math.min(1, (clientX - bounds.left) / Math.max(1, bounds.width))),
    y: Math.max(0, Math.min(1, (clientY - bounds.top) / Math.max(1, bounds.height))),
  }
}

export function availableProviders(providers: ImageProvider[], operation: ImageOperation) {
  return providers.filter((provider) => provider.configured && provider.operations.includes(operation))
}

export function appendRevision(history: ImageAsset[], position: number, next: ImageAsset): ImageAsset[] {
  return [...history.slice(0, position + 1), next]
}
