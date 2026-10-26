import type { Auth } from '../../auth'
import type { ImageAsset, ImageComment, ImageEdit, ImageProvider, Point } from '../model/image'

const assetPath = (id: string) => `/api/images/assets/${encodeURIComponent(id)}`

export function imageContentPath(id: string): string {
  return `${assetPath(id)}/content`
}

export function createImageClient(auth: Pick<Auth, 'authenticatedRequest'>) {
  const request = auth.authenticatedRequest
  return {
    providers: () => request<ImageProvider[]>('/api/images/providers'),
    list: () => request<ImageAsset[]>('/api/images/assets?limit=50'),
    upload: (file: File, purpose: 'image' | 'mask' = 'image') => {
      const body = new FormData()
      body.append('file', file)
      body.append('purpose', purpose)
      return request<ImageAsset>('/api/images/assets', { method: 'POST', body })
    },
    edit: (id: string, edit: ImageEdit) =>
      request<ImageAsset>(`${assetPath(id)}/edits`, { method: 'POST', body: JSON.stringify(edit) }),
    comments: (id: string) => request<ImageComment[]>(`${assetPath(id)}/comments`),
    addComment: (id: string, comment: Point & { text: string }) =>
      request<ImageComment>(`${assetPath(id)}/comments`, { method: 'POST', body: JSON.stringify(comment) }),
    deleteComment: (id: string, commentId: string) =>
      request<void>(`${assetPath(id)}/comments/${encodeURIComponent(commentId)}`, { method: 'DELETE' }),
  }
}

export type ImageClient = ReturnType<typeof createImageClient>
