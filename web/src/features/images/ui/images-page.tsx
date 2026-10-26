import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { ImagePlus, RefreshCw, Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../../auth'
import { ApiRequestError } from '../../../lib/api-client'
import { createImageClient, imageContentPath } from '../infrastructure/image-client'
import type { ImageAsset, ImageProvider } from '../model/image'
import { ImageEditor } from './image-editor'
import './images.css'

export function ImagesPage() {
  const { t } = useTranslation('images')
  const { authenticatedRequest } = useAuth()
  const client = useMemo(() => createImageClient({ authenticatedRequest }), [authenticatedRequest])
  const [assets, setAssets] = useState<ImageAsset[]>([])
  const [providers, setProviders] = useState<ImageProvider[]>([])
  const [selected, setSelected] = useState<ImageAsset | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const uploadLock = useRef(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    void Promise.all([client.list(), client.providers()])
      .then(([images, models]) => {
        if (active) {
          setAssets(images)
          setProviders(models)
        }
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [client, reload, t])

  const saveAsset = (asset: ImageAsset) => {
    setAssets((current) => [asset, ...current.filter((item) => item.id !== asset.id)].slice(0, 50))
  }

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || uploadLock.current) return
    setError(null)
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      setError(t('errors.invalidFile'))
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setError(t('errors.fileTooLarge'))
      return
    }
    uploadLock.current = true
    setUploading(true)
    try {
      const asset = await client.upload(file)
      saveAsset(asset)
      setSelected(asset)
    } catch (cause) {
      setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
    } finally {
      uploadLock.current = false
      setUploading(false)
    }
  }

  return (
    <section className="space-y-6" aria-busy={loading || uploading}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{t('title')}</h1>
          <p className="text-muted-foreground">{t('description')}</p>
        </div>
        <label className={`image-button image-button-primary relative ${uploading ? 'opacity-50' : ''}`}>
          <Upload size={17} aria-hidden="true" />
          {uploading ? t('saving') : t('upload')}
          <input
            className="absolute inset-0 cursor-pointer opacity-0"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label={t('upload')}
            disabled={uploading}
            onChange={(event) => void upload(event)}
          />
        </label>
      </div>
      <p className="text-sm text-muted-foreground">{t('uploadHint')}</p>
      {error && (
        <div role="alert" className="image-error flex flex-wrap items-center justify-between gap-3">
          <span>{error}</span>
          <button className="image-button" onClick={() => setReload((value) => value + 1)}>
            <RefreshCw size={15} />
            {t('retry')}
          </button>
        </div>
      )}
      {loading ? (
        <p role="status">{t('loading')}</p>
      ) : assets.length === 0 ? (
        <div className="flex min-h-64 flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border bg-card text-muted-foreground">
          <ImagePlus size={40} strokeWidth={1.2} aria-hidden="true" />
          <p>{t('empty')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {assets.map((asset) => (
            <button
              key={asset.id}
              className="image-asset-card text-left"
              onClick={() => setSelected(asset)}
              aria-label={t('open', { name: asset.filename })}
            >
              <div className="image-checkerboard flex aspect-[16/10] items-center justify-center overflow-hidden rounded-t-xl">
                <img
                  src={imageContentPath(asset.id)}
                  alt={asset.filename}
                  loading="lazy"
                  className="h-full w-full object-contain"
                />
              </div>
              <div className="space-y-1 border-t border-border p-4">
                <p className="truncate font-medium">{asset.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {asset.width} × {asset.height} · PNG
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
      {selected && (
        <ImageEditor
          key={selected.id}
          initialAsset={selected}
          providers={providers}
          client={client}
          onSave={saveAsset}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  )
}
