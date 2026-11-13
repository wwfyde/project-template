import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiRequestError } from '../../../lib/api-client'
import type { SkillClient } from '../infrastructure/skill-client'
import { findManifest, formatSkillBytes, type SkillFileData, type SkillTreeData } from '../model/skill'
import { SkillFilePreview } from './skill-file-preview'
import { SkillTree } from './skill-tree'

export type SkillPreviewProps = {
  client: Pick<SkillClient, 'tree' | 'file'>
  skillId: string
  version?: string
}

export function SkillPreview(props: SkillPreviewProps) {
  // Reset both the selection and loaded data immediately when the target changes.
  return <VersionPreview key={`${props.skillId}:${props.version ?? 'default'}`} {...props} />
}

function VersionPreview({ client, skillId, version }: SkillPreviewProps) {
  const { t } = useTranslation('skills')
  const [tree, setTree] = useState<SkillTreeData | null>(null)
  const [path, setPath] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)
    setTree(null)
    setPath(null)
    void client
      .tree(skillId, version, controller.signal)
      .then((data) => {
        if (active) {
          setTree(data)
          setPath(findManifest(data.nodes))
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
      controller.abort()
    }
  }, [client, skillId, version, reload, t])

  if (loading)
    return (
      <p role="status" className="p-5 text-sm text-muted-foreground">
        {t('loading')}
      </p>
    )
  if (error)
    return (
      <div role="alert" className="skill-error space-y-3">
        <p>{error}</p>
        <button type="button" className="skill-button" onClick={() => setReload((value) => value + 1)}>
          {t('retry')}
        </button>
      </div>
    )
  if (!tree) return null

  return (
    <div className="skill-preview-grid">
      <aside className="min-w-0 border-b border-border lg:border-r lg:border-b-0">
        <div className="space-y-1 border-b border-border p-3">
          <h3 className="text-sm font-medium">{t('files')}</h3>
          <p className="text-xs text-muted-foreground">
            {t('fileCount', { count: tree.file_count, size: formatSkillBytes(tree.total_bytes) })}
          </p>
        </div>
        <SkillTree nodes={tree.nodes} selectedPath={path} onSelect={(node) => setPath(node.path)} />
      </aside>
      {path ? (
        <RemoteFilePreview key={path} client={client} skillId={skillId} version={tree.version} path={path} />
      ) : (
        <SkillFilePreview file={null} />
      )}
    </div>
  )
}

function RemoteFilePreview({ client, skillId, version, path }: SkillPreviewProps & { path: string }) {
  const { t } = useTranslation('skills')
  const [file, setFile] = useState<SkillFileData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setFile(null)
    setError(null)
    void client
      .file(skillId, path, version, controller.signal)
      .then((data) => {
        if (active) setFile(data)
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof ApiRequestError ? cause.message : t('errors.requestFailed'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [client, skillId, version, path, reload, t])

  return (
    <SkillFilePreview file={file} loading={loading} error={error} onRetry={() => setReload((value) => value + 1)} />
  )
}
