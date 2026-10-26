import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Eraser,
  GripVertical,
  MessageSquare,
  Paintbrush,
  Redo2,
  ScanLine,
  Scaling,
  Trash2,
  Undo2,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { ApiRequestError } from '../../../lib/api-client'
import { imageContentPath, type ImageClient } from '../infrastructure/image-client'
import {
  appendRevision,
  availableProviders,
  normalizePoint,
  type ImageAsset,
  type ImageComment,
  type ImageEdit,
  type ImageOperation,
  type ImageProvider,
  type Markup,
  type Point,
} from '../model/image'

type Tool = ImageOperation | 'comment'
type Props = {
  initialAsset: ImageAsset
  providers: ImageProvider[]
  client: ImageClient
  onSave: (asset: ImageAsset) => void
  onClose: () => void
}

const toolbar = [
  { id: 'markup', icon: Paintbrush },
  { id: 'comment', icon: MessageSquare },
  { id: 'remove_background', icon: ScanLine },
  { id: 'erase', icon: Eraser },
  { id: 'resize', icon: Scaling },
] as const

function pathData(mark: Markup, width: number, height: number) {
  return mark.points.map((p, index) => `${index === 0 ? 'M' : 'L'} ${p.x * width} ${p.y * height}`).join(' ')
}

function Mark({ mark, asset, mask = false }: { mark: Markup; asset: ImageAsset; mask?: boolean }) {
  const first = mark.points[0]
  const last = mark.points.at(-1) ?? first
  const color = mask ? '#ef4444' : mark.color
  const lineProps = {
    fill: 'none',
    stroke: color,
    strokeWidth: mark.width,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  if (mark.kind === 'path') {
    return mark.points.length === 1 ? (
      <circle cx={first.x * asset.width} cy={first.y * asset.height} r={mark.width / 2} fill={color} />
    ) : (
      <path d={pathData(mark, asset.width, asset.height)} {...lineProps} />
    )
  }
  if (mark.kind === 'text')
    return (
      <text
        x={first.x * asset.width}
        y={first.y * asset.height}
        fill={color}
        fontSize={mark.width}
        dominantBaseline="hanging"
      >
        {mark.text}
      </text>
    )
  const x = Math.min(first.x, last.x) * asset.width
  const y = Math.min(first.y, last.y) * asset.height
  const width = Math.abs(first.x - last.x) * asset.width
  const height = Math.abs(first.y - last.y) * asset.height
  return mark.kind === 'rectangle' ? (
    <rect x={x} y={y} width={width} height={height} {...lineProps} />
  ) : (
    <ellipse cx={x + width / 2} cy={y + height / 2} rx={width / 2} ry={height / 2} {...lineProps} />
  )
}

async function createMask(asset: ImageAsset, strokes: Markup[]): Promise<File> {
  const canvas = document.createElement('canvas')
  canvas.width = asset.width
  canvas.height = asset.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable')
  context.fillStyle = '#000000'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.fillStyle = '#ffffff'
  context.strokeStyle = '#ffffff'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  for (const stroke of strokes) {
    const point = stroke.points[0]
    context.lineWidth = stroke.width
    if (stroke.points.length === 1) {
      context.beginPath()
      context.arc(point.x * asset.width, point.y * asset.height, stroke.width / 2, 0, 2 * Math.PI)
      context.fill()
    } else {
      context.beginPath()
      context.moveTo(point.x * asset.width, point.y * asset.height)
      for (const next of stroke.points.slice(1)) context.lineTo(next.x * asset.width, next.y * asset.height)
      context.stroke()
    }
  }
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((value) => (value ? resolve(value) : reject(new Error('Mask encoding failed'))), 'image/png'),
  )
  return new File([blob], 'erase-mask.png', { type: 'image/png' })
}

export function ImageEditor({ initialAsset, providers, client, onSave, onClose }: Props) {
  const { t } = useTranslation('images')
  const [history, setHistory] = useState([initialAsset])
  const [position, setPosition] = useState(0)
  const asset = history[position]
  const [tool, setTool] = useState<Tool>('markup')
  const [kind, setKind] = useState<Markup['kind']>('path')
  const [color, setColor] = useState('#ef4444')
  const [brush, setBrush] = useState(12)
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<Markup[]>([])
  const [redo, setRedo] = useState<Markup[]>([])
  const [drawing, setDrawing] = useState<Markup | null>(null)
  const activeStroke = useRef<Markup | null>(null)
  const activePointer = useRef<number | null>(null)
  const [providerId, setProviderId] = useState('')
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [width, setWidth] = useState(String(asset.width))
  const [height, setHeight] = useState(String(asset.height))
  const [fit, setFit] = useState<'contain' | 'cover' | 'stretch'>('contain')
  const [transparent, setTransparent] = useState(true)
  const [background, setBackground] = useState('#ffffff')
  const [comments, setComments] = useState<ImageComment[]>([])
  const [commentText, setCommentText] = useState('')
  const [anchor, setAnchor] = useState<Point>({ x: 0.5, y: 0.5 })
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentsReload, setCommentsReload] = useState(0)
  const [commentsError, setCommentsError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const busyLock = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const operation = tool === 'comment' ? 'markup' : tool
  const candidates = useMemo(() => availableProviders(providers, operation), [providers, operation])
  const provider = candidates.find((item) => item.id === providerId) ?? candidates[0]
  const selectedModel = provider?.models.includes(model)
    ? model
    : (provider?.default_model ?? provider?.models[0] ?? '')
  const isAI = tool === 'erase' || tool === 'remove_background'
  const hasDraft = draft.length > 0 || drawing !== null

  useEffect(() => {
    setWidth(String(asset.width))
    setHeight(String(asset.height))
    setLoaded(false)
    setComments([])
    setCommentText('')
    setAnchor({ x: 0.5, y: 0.5 })
  }, [asset.id, asset.width, asset.height])

  useEffect(() => {
    if (tool !== 'comment') return
    let active = true
    setCommentsLoading(true)
    setCommentsError(null)
    void client
      .comments(asset.id)
      .then((items) => {
        if (active) setComments(items)
      })
      .catch((cause: unknown) => {
        if (active) setCommentsError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
      })
      .finally(() => {
        if (active) setCommentsLoading(false)
      })
    return () => {
      active = false
    }
  }, [asset.id, client, tool, commentsReload, t])

  const reportError = (cause: unknown) => {
    setError(
      cause instanceof ApiRequestError
        ? `${cause.message} (${t('errors.requestId', { id: cause.requestId })})`
        : t('errors.requestFailed'),
    )
  }

  const clearDraft = () => {
    setDraft([])
    setRedo([])
    setDrawing(null)
    activeStroke.current = null
    activePointer.current = null
    setError(null)
  }

  const chooseTool = (next: Tool) => {
    if (busyLock.current || next === tool) return
    if (hasDraft) {
      setError(t('draftWarning'))
      return
    }
    clearDraft()
    setTool(next)
    setProviderId('')
    setModel('')
  }

  const close = () => {
    if (busyLock.current) return
    if (hasDraft) {
      setError(t('draftWarning'))
      return
    }
    onClose()
  }

  const moveVersion = (next: number) => {
    if (busyLock.current || next < 0 || next >= history.length) return
    if (hasDraft) {
      setError(t('draftWarning'))
      return
    }
    clearDraft()
    setPosition(next)
  }

  const startPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (busyLock.current || !loaded || event.button !== 0 || activePointer.current !== null) return
    const point = normalizePoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect())
    if (tool === 'comment') {
      setAnchor(point)
      return
    }
    if (tool !== 'markup' && tool !== 'erase') return
    if (draft.length >= 200) return
    if (kind === 'text' && tool === 'markup' && !text.trim()) {
      setError(t('errors.emptyText'))
      return
    }
    setError(null)
    const mark: Markup = {
      kind: tool === 'erase' ? 'path' : kind,
      points: [point],
      color,
      width: brush,
      ...(tool === 'markup' && kind === 'text' ? { text: text.trim() } : {}),
    }
    if (mark.kind === 'text') {
      setDraft((items) => [...items, mark])
      setRedo([])
      return
    }
    activePointer.current = event.pointerId
    event.currentTarget.setPointerCapture(event.pointerId)
    activeStroke.current = mark
    setDrawing(mark)
  }

  const movePointer = (event: PointerEvent<SVGSVGElement>) => {
    const previous = activeStroke.current
    if (!previous || activePointer.current !== event.pointerId) return
    const point = normalizePoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect())
    let points = previous.kind === 'path' ? [...previous.points, point] : [previous.points[0], point]
    // Bound one long stroke without changing its endpoints.
    if (points.length > 2000) points = [...points.filter((_, index) => index % 2 === 0), point]
    const next = { ...previous, points }
    activeStroke.current = next
    setDrawing(next)
  }

  const endPointer = (event: PointerEvent<SVGSVGElement>, cancelled = false) => {
    if (activePointer.current !== event.pointerId) return
    const stroke = activeStroke.current
    activeStroke.current = null
    activePointer.current = null
    setDrawing(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    if (stroke && !cancelled && (stroke.kind === 'path' || stroke.points.length === 2)) {
      setDraft((items) => [...items, stroke])
      setRedo([])
    }
  }

  const apply = async () => {
    if (busyLock.current || !loaded || tool === 'comment') return
    setError(null)
    if (tool === 'markup' && draft.length === 0) return setError(t('errors.emptyMarkup'))
    if (tool === 'erase' && draft.length === 0) return setError(t('errors.emptySelection'))
    if (isAI && !provider) return setError(t('unavailable'))
    const requestedWidth = Number(width)
    const requestedHeight = Number(height)
    if (
      tool === 'resize' &&
      (![requestedWidth, requestedHeight].every((value) => Number.isInteger(value) && value >= 1 && value <= 8192) ||
        requestedWidth * requestedHeight > 16_000_000)
    ) {
      setError(t('errors.invalidDimensions'))
      return
    }
    busyLock.current = true
    setBusy(true)
    try {
      const edit: ImageEdit = { operation: tool, provider: isAI ? provider!.id : 'local' }
      if (isAI && selectedModel) edit.model = selectedModel
      if (tool === 'markup') edit.markup = draft
      if (tool === 'resize')
        Object.assign(edit, {
          width: requestedWidth,
          height: requestedHeight,
          fit,
          background: transparent ? 'transparent' : background,
        })
      if (tool === 'erase') {
        const mask = await client.upload(await createMask(asset, draft), 'mask')
        edit.mask_asset_id = mask.id
        if (prompt.trim()) edit.prompt = prompt.trim()
      }
      const result = await client.edit(asset.id, edit)
      setHistory((previous) => appendRevision(previous, position, result))
      setPosition(position + 1)
      clearDraft()
      onSave(result)
    } catch (cause) {
      reportError(cause)
    } finally {
      busyLock.current = false
      setBusy(false)
    }
  }

  const saveComment = async () => {
    if (busyLock.current) return
    if (!commentText.trim() || commentText.trim().length > 2000) {
      setError(t('errors.invalidComment'))
      return
    }
    busyLock.current = true
    setBusy(true)
    setError(null)
    try {
      const comment = await client.addComment(asset.id, { ...anchor, text: commentText.trim() })
      setComments((previous) => [...previous, comment])
      setCommentText('')
    } catch (cause) {
      reportError(cause)
    } finally {
      busyLock.current = false
      setBusy(false)
    }
  }

  const deleteComment = async (id: string) => {
    if (busyLock.current) return
    busyLock.current = true
    setBusy(true)
    setError(null)
    try {
      await client.deleteComment(asset.id, id)
      setComments((previous) => previous.filter((item) => item.id !== id))
    } catch (cause) {
      reportError(cause)
    } finally {
      busyLock.current = false
      setBusy(false)
    }
  }

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm" />
        <Dialog.Popup className="image-preview-dialog" aria-busy={busy}>
          <header className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Dialog.Title className="truncate font-semibold">{asset.filename}</Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-muted-foreground">
                {t('previewDescription')}
              </Dialog.Description>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <a
                className="image-button"
                href={`${imageContentPath(asset.id)}?download=true`}
                download={asset.filename}
                aria-label={t('download')}
                title={t('download')}
              >
                <Download size={18} />
                <span className="hidden sm:inline">{t('download')}</span>
              </a>
              <button
                className="image-button"
                onClick={close}
                disabled={busy}
                aria-label={t('close')}
                title={t('close')}
              >
                <X size={18} />
              </button>
            </div>
          </header>
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              {asset.width} × {asset.height} · PNG
            </span>
            <div className="flex items-center gap-2">
              <button
                className="image-button !min-h-7 !p-1"
                disabled={busy || position === 0}
                onClick={() => moveVersion(position - 1)}
                aria-label={t('previousVersion')}
                title={t('previousVersion')}
              >
                <ChevronLeft size={16} />
              </button>
              <span aria-live="polite">{t('version', { current: position + 1, total: history.length })}</span>
              <button
                className="image-button !min-h-7 !p-1"
                disabled={busy || position >= history.length - 1}
                onClick={() => moveVersion(position + 1)}
                aria-label={t('nextVersion')}
                title={t('nextVersion')}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
          <div className="image-preview-stage">
            <div className="image-preview-surface image-checkerboard">
              <img
                key={asset.id}
                src={imageContentPath(asset.id)}
                alt={asset.filename}
                onLoad={() => setLoaded(true)}
                onError={() => {
                  setLoaded(false)
                  setError(t('errors.imageFailed'))
                }}
                draggable={false}
              />
              {loaded && ['markup', 'erase', 'comment'].includes(tool) && (
                <svg
                  className="image-preview-overlay"
                  viewBox={`0 0 ${asset.width} ${asset.height}`}
                  aria-label={t(tool === 'comment' ? 'commentHint' : tool === 'erase' ? 'eraseHint' : 'drawHint')}
                  onPointerDown={startPointer}
                  onPointerMove={movePointer}
                  onPointerUp={(event) => endPointer(event)}
                  onPointerCancel={(event) => endPointer(event, true)}
                >
                  <g opacity={tool === 'erase' ? 0.5 : 1}>
                    {draft.map((mark, index) => (
                      <Mark key={index} mark={mark} asset={asset} mask={tool === 'erase'} />
                    ))}
                    {drawing && <Mark mark={drawing} asset={asset} mask={tool === 'erase'} />}
                  </g>
                  {tool === 'comment' && (
                    <g>
                      {comments.map((comment, index) => (
                        <g key={comment.id}>
                          <circle
                            cx={comment.x * asset.width}
                            cy={comment.y * asset.height}
                            r={Math.max(asset.width / 90, 12)}
                            fill="#2563eb"
                          />
                          <text
                            x={comment.x * asset.width}
                            y={comment.y * asset.height}
                            fill="white"
                            dominantBaseline="central"
                            textAnchor="middle"
                            fontSize={Math.max(asset.width / 90, 12)}
                          >
                            {index + 1}
                          </text>
                        </g>
                      ))}
                      <circle
                        cx={anchor.x * asset.width}
                        cy={anchor.y * asset.height}
                        r={Math.max(asset.width / 75, 15)}
                        fill="none"
                        stroke="#f97316"
                        strokeWidth={Math.max(asset.width / 350, 3)}
                        strokeDasharray="6 4"
                      />
                    </g>
                  )}
                </svg>
              )}
            </div>
          </div>
          <div className="image-toolbar" role="group" aria-label={t('preview')}>
            <GripVertical size={20} className="hidden shrink-0 sm:block" aria-hidden="true" />
            {toolbar.map(({ id, icon: Icon }) => (
              <button key={id} type="button" onClick={() => chooseTool(id)} disabled={busy} aria-pressed={tool === id}>
                <Icon size={21} strokeWidth={1.7} aria-hidden="true" />
                <span>{t(id)}</span>
              </button>
            ))}
          </div>
          {error && (
            <p className="image-error" role="alert">
              {error}
            </p>
          )}
          <section className="image-editor-panel space-y-3" aria-label={t(tool)}>
            {(tool === 'markup' || tool === 'erase') && (
              <>
                <div className="flex flex-wrap items-end gap-3">
                  {tool === 'markup' && (
                    <label className="image-field-label">
                      {t('markup')}
                      <select
                        className="image-field"
                        disabled={busy}
                        value={kind}
                        onChange={(event) => {
                          const next = event.target.value as Markup['kind']
                          setKind(next)
                          if (next === 'text') setBrush(32)
                        }}
                      >
                        <option value="path">{t('pen')}</option>
                        <option value="text">{t('text')}</option>
                        <option value="rectangle">{t('rectangle')}</option>
                        <option value="ellipse">{t('ellipse')}</option>
                      </select>
                    </label>
                  )}
                  {tool === 'markup' && (
                    <label className="image-field-label">
                      {t('color')}
                      <input
                        type="color"
                        className="h-9 w-12 rounded border border-border"
                        value={color}
                        disabled={busy}
                        onChange={(event) => setColor(event.target.value)}
                      />
                    </label>
                  )}
                  <label className="image-field-label">
                    {t('brushSize')}
                    <input
                      className="image-field w-24"
                      type="number"
                      min={1}
                      max={128}
                      value={brush}
                      disabled={busy}
                      onChange={(event) => setBrush(Math.max(1, Math.min(128, Number(event.target.value) || 1)))}
                    />
                  </label>
                  {tool === 'markup' && kind === 'text' && (
                    <label className="image-field-label min-w-48 flex-1">
                      {t('text')}
                      <input
                        className="image-field"
                        maxLength={500}
                        value={text}
                        disabled={busy}
                        placeholder={t('textPlaceholder')}
                        onChange={(event) => setText(event.target.value)}
                      />
                    </label>
                  )}
                  <div className="flex gap-1">
                    <button
                      className="image-button"
                      disabled={busy || draft.length === 0}
                      aria-label={t('undo')}
                      title={t('undo')}
                      onClick={() => {
                        setRedo((items) => [...items, draft.at(-1)!])
                        setDraft((items) => items.slice(0, -1))
                      }}
                    >
                      <Undo2 size={17} />
                    </button>
                    <button
                      className="image-button"
                      disabled={busy || redo.length === 0}
                      aria-label={t('redo')}
                      title={t('redo')}
                      onClick={() => {
                        setDraft((items) => [...items, redo.at(-1)!])
                        setRedo((items) => items.slice(0, -1))
                      }}
                    >
                      <Redo2 size={17} />
                    </button>
                    <button
                      className="image-button"
                      disabled={busy || (!hasDraft && redo.length === 0)}
                      onClick={clearDraft}
                    >
                      {t('resetDraft')}
                    </button>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">{t(tool === 'erase' ? 'eraseHint' : 'drawHint')}</p>
              </>
            )}
            {isAI && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="image-field-label">
                    {t('provider')}
                    <select
                      className="image-field"
                      value={provider?.id ?? ''}
                      disabled={busy || candidates.length === 0}
                      onChange={(event) => {
                        setProviderId(event.target.value)
                        setModel('')
                      }}
                    >
                      <option value="" disabled>
                        —
                      </option>
                      {candidates.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="image-field-label">
                    {t('model')}
                    <select
                      className="image-field"
                      value={selectedModel}
                      disabled={busy || !provider || provider.models.length === 0}
                      onChange={(event) => setModel(event.target.value)}
                    >
                      {provider?.models.length ? (
                        provider.models.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))
                      ) : (
                        <option value="">—</option>
                      )}
                    </select>
                  </label>
                </div>
                {!provider ? (
                  <p role="status" className="text-sm text-muted-foreground">
                    {t('unavailable')}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">{t('modelCost')}</p>
                )}
                {tool === 'erase' && provider?.mask_mode === 'reference' && (
                  <p className="text-xs text-muted-foreground">{t('referenceMask')}</p>
                )}
                {tool === 'erase' && (
                  <label className="image-field-label">
                    {t('prompt')}
                    <input
                      className="image-field"
                      maxLength={2000}
                      value={prompt}
                      disabled={busy}
                      onChange={(event) => setPrompt(event.target.value)}
                      placeholder={t('promptPlaceholder')}
                    />
                  </label>
                )}
              </>
            )}
            {tool === 'resize' && (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="image-field-label">
                    {t('width')}
                    <input
                      className="image-field"
                      type="number"
                      min={1}
                      max={8192}
                      step={1}
                      value={width}
                      disabled={busy}
                      onChange={(event) => setWidth(event.target.value)}
                    />
                  </label>
                  <label className="image-field-label">
                    {t('height')}
                    <input
                      className="image-field"
                      type="number"
                      min={1}
                      max={8192}
                      step={1}
                      value={height}
                      disabled={busy}
                      onChange={(event) => setHeight(event.target.value)}
                    />
                  </label>
                  <label className="image-field-label">
                    {t('fit')}
                    <select
                      className="image-field"
                      value={fit}
                      disabled={busy}
                      onChange={(event) => setFit(event.target.value as typeof fit)}
                    >
                      <option value="contain">{t('contain')}</option>
                      <option value="cover">{t('cover')}</option>
                      <option value="stretch">{t('stretch')}</option>
                    </select>
                  </label>
                </div>
                {fit === 'contain' && (
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={transparent}
                        disabled={busy}
                        onChange={(event) => setTransparent(event.target.checked)}
                      />
                      {t('transparent')}
                    </label>
                    {!transparent && (
                      <label className="flex items-center gap-2">
                        {t('background')}
                        <input
                          type="color"
                          value={background}
                          disabled={busy}
                          onChange={(event) => setBackground(event.target.value)}
                        />
                      </label>
                    )}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">{t('resizeHint')}</p>
              </>
            )}
            {tool === 'comment' && (
              <>
                <p className="text-xs text-muted-foreground">{t('commentHint')}</p>
                <div className="grid gap-3 sm:grid-cols-[1fr_1fr_2fr]">
                  <label className="image-field-label">
                    {t('positionX')}
                    <input
                      className="image-field"
                      type="number"
                      min={0}
                      max={100}
                      step={0.1}
                      disabled={busy}
                      value={Math.round(anchor.x * 1000) / 10}
                      onChange={(event) =>
                        setAnchor((point) => ({
                          ...point,
                          x: Math.max(0, Math.min(100, Number(event.target.value) || 0)) / 100,
                        }))
                      }
                    />
                  </label>
                  <label className="image-field-label">
                    {t('positionY')}
                    <input
                      className="image-field"
                      type="number"
                      min={0}
                      max={100}
                      step={0.1}
                      disabled={busy}
                      value={Math.round(anchor.y * 1000) / 10}
                      onChange={(event) =>
                        setAnchor((point) => ({
                          ...point,
                          y: Math.max(0, Math.min(100, Number(event.target.value) || 0)) / 100,
                        }))
                      }
                    />
                  </label>
                  <label className="image-field-label">
                    {t('comment')}
                    <input
                      className="image-field"
                      maxLength={2000}
                      value={commentText}
                      disabled={busy}
                      placeholder={t('commentPlaceholder')}
                      onChange={(event) => setCommentText(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                          event.preventDefault()
                          void saveComment()
                        }
                      }}
                    />
                  </label>
                </div>
                <div className="flex justify-end">
                  <button
                    className="image-button image-button-primary"
                    disabled={busy || !commentText.trim() || !loaded}
                    onClick={() => void saveComment()}
                  >
                    {busy ? t('saving') : t('addComment')}
                  </button>
                </div>
                {commentsError && (
                  <div className="image-error flex items-center justify-between gap-3" role="alert">
                    <span>{commentsError}</span>
                    <button className="image-button" onClick={() => setCommentsReload((value) => value + 1)}>
                      {t('retry')}
                    </button>
                  </div>
                )}
                {commentsLoading ? (
                  <p role="status">{t('loading')}</p>
                ) : comments.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t('noComments')}</p>
                ) : (
                  <ol className="image-comment-list">
                    {comments.map((comment, index) => (
                      <li key={comment.id}>
                        <button
                          className="flex min-w-0 items-start gap-2 text-left"
                          onClick={() => setAnchor({ x: comment.x, y: comment.y })}
                        >
                          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs text-white">
                            {index + 1}
                          </span>
                          <span className="whitespace-pre-wrap break-words">{comment.text}</span>
                        </button>
                        <button
                          className="image-button !p-1.5"
                          disabled={busy}
                          aria-label={t('deleteComment')}
                          title={t('deleteComment')}
                          onClick={() => void deleteComment(comment.id)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </>
            )}
            {tool !== 'comment' && (
              <div className="flex justify-end">
                <button
                  className="image-button image-button-primary"
                  disabled={
                    busy ||
                    !loaded ||
                    drawing !== null ||
                    (isAI && !provider) ||
                    ((tool === 'markup' || tool === 'erase') && draft.length === 0)
                  }
                  onClick={() => void apply()}
                >
                  {busy
                    ? t('saving')
                    : t(
                        tool === 'markup'
                          ? 'saveMarkup'
                          : tool === 'erase'
                            ? 'eraseSelection'
                            : tool === 'remove_background'
                              ? 'removeBackground'
                              : 'apply',
                      )}
                </button>
              </div>
            )}
            {busy && (
              <p role="status" className="text-xs text-muted-foreground">
                {t('saving')}
              </p>
            )}
          </section>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
