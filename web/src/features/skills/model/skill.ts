export type Skill = {
  id: string
  object: 'skill'
  created_at: number
  name: string
  description: string
  default_version: string
  latest_version: string
}

export type SkillVersion = {
  id: string
  object: 'skill.version'
  created_at: number
  name: string
  description: string
  skill_id: string
  version: string
}

export type SkillList<T> = {
  object: 'list'
  data: T[]
  first_id: string | null
  last_id: string | null
  has_more: boolean
}

export type DeletedSkill = { id: string; object: 'skill.deleted'; deleted: boolean }
export type DeletedSkillVersion = { id: string; object: 'skill.version.deleted'; deleted: boolean; version: string }

export type SkillTreeNode = {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number | null
  media_type: string | null
  children: SkillTreeNode[]
}

export type SkillTreeData = {
  object: 'skill.tree'
  skill_id: string
  version: string
  nodes: SkillTreeNode[]
  file_count: number
  total_bytes: number
}

export type SkillFileData = {
  object: 'skill.file'
  skill_id: string
  version: string
  path: string
  size: number
  media_type: string
  encoding: 'utf-8' | null
  content: string | null
  truncated: boolean
  reason: string | null
}

export type SkillUpload = { kind: 'zip'; file: File } | { kind: 'directory'; files: File[] }

export function validateSkillUpload(
  upload: SkillUpload,
): 'invalidZip' | 'fileTooLarge' | 'tooManyFiles' | 'emptyUpload' | null {
  if (upload.kind === 'zip') {
    if (!upload.file.name.toLowerCase().endsWith('.zip')) return 'invalidZip'
    return upload.file.size > 50 * 1024 * 1024 ? 'fileTooLarge' : null
  }
  if (!upload.files.length) return 'emptyUpload'
  if (upload.files.length > 500) return 'tooManyFiles'
  if (upload.files.some((file) => file.size > 25 * 1024 * 1024)) return 'fileTooLarge'
  return null
}

export function findManifest(nodes: SkillTreeNode[]): string | null {
  for (const node of nodes) {
    if (node.type === 'file' && node.name.toLowerCase() === 'skill.md') return node.path
    const nested = findManifest(node.children)
    if (nested) return nested
  }
  return null
}

export function mergeSkillPage<T extends { id: string }>(current: T[], incoming: T[]): T[] {
  const byId = new Map(current.map((item) => [item.id, item]))
  incoming.forEach((item) => byId.set(item.id, item))
  return [...byId.values()]
}

export function formatSkillBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}
