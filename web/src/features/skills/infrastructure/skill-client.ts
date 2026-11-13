import type { Auth } from '../../auth'
import type {
  DeletedSkill,
  DeletedSkillVersion,
  Skill,
  SkillFileData,
  SkillList,
  SkillTreeData,
  SkillUpload,
  SkillVersion,
} from '../model/skill'

const skillPath = (id: string) => `/api/skills/${encodeURIComponent(id)}`
const versionPath = (id: string, version?: string) =>
  version === undefined ? skillPath(id) : `${skillPath(id)}/versions/${encodeURIComponent(version)}`

export function skillContentPath(id: string, version?: string): string {
  return `${versionPath(id, version)}/content`
}

function uploadBody(upload: SkillUpload, makeDefault?: boolean): FormData {
  const body = new FormData()
  if (upload.kind === 'zip') {
    body.append('files', upload.file)
  } else {
    for (const file of upload.files) {
      body.append('files[]', file, file.webkitRelativePath || file.name)
    }
  }
  if (makeDefault !== undefined) body.append('default', String(makeDefault))
  return body
}

type ListOptions = { after?: string; limit?: number; order?: 'asc' | 'desc'; signal?: AbortSignal }

function listQuery({ after, limit = 20, order = 'desc' }: ListOptions): string {
  const query = new URLSearchParams({ limit: String(limit), order })
  if (after) query.set('after', after)
  return query.toString()
}

export function createSkillClient(auth: Pick<Auth, 'authenticatedRequest'>) {
  const request = auth.authenticatedRequest
  return {
    list: (options: ListOptions = {}) =>
      request<SkillList<Skill>>(`/api/skills?${listQuery(options)}`, { signal: options.signal }),
    get: (id: string, signal?: AbortSignal) => request<Skill>(skillPath(id), { signal }),
    create: (upload: SkillUpload) => request<Skill>('/api/skills', { method: 'POST', body: uploadBody(upload) }),
    setDefault: (id: string, version: string) =>
      request<Skill>(skillPath(id), { method: 'POST', body: JSON.stringify({ default_version: version }) }),
    delete: (id: string) => request<DeletedSkill>(skillPath(id), { method: 'DELETE' }),
    versions: (id: string, options: ListOptions = {}) =>
      request<SkillList<SkillVersion>>(`${skillPath(id)}/versions?${listQuery(options)}`, { signal: options.signal }),
    getVersion: (id: string, version: string, signal?: AbortSignal) =>
      request<SkillVersion>(versionPath(id, version), { signal }),
    createVersion: (id: string, upload: SkillUpload, makeDefault = false) =>
      request<SkillVersion>(`${skillPath(id)}/versions`, {
        method: 'POST',
        body: uploadBody(upload, makeDefault),
      }),
    deleteVersion: (id: string, version: string) =>
      request<DeletedSkillVersion>(versionPath(id, version), { method: 'DELETE' }),
    tree: (id: string, version?: string, signal?: AbortSignal) =>
      request<SkillTreeData>(`${versionPath(id, version)}/tree`, { signal }),
    file: (id: string, path: string, version?: string, signal?: AbortSignal) =>
      request<SkillFileData>(`${versionPath(id, version)}/files?${new URLSearchParams({ path })}`, { signal }),
  }
}

export type SkillClient = ReturnType<typeof createSkillClient>
