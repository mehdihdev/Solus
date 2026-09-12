import { api, type ApiClient } from './client'

export interface SourceRevisionPage {
  supported: boolean
  kind: 'git_branch' | null
  items: { name: string; commit: string }[]
  next_page: number | null
}

export interface SourceView {
  base_source_id: string
  status: 'default' | 'pending' | 'ready' | 'failed'
  source_id: string
  branch: string | null
  commit: string | null
  error: string | null
}

function sourcePath(projectId: string, sourceId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}`
}

export function listSourceRevisions(
  projectId: string,
  sourceId: string,
  page = 1,
  client: ApiClient = api
): Promise<SourceRevisionPage> {
  return client.request(`${sourcePath(projectId, sourceId)}/revisions?page=${page}`)
}

export function getSourceView(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<SourceView> {
  return client.request(`${sourcePath(projectId, sourceId)}/view`)
}

export function selectSourceView(
  projectId: string,
  sourceId: string,
  branch: string,
  client: ApiClient = api
): Promise<SourceView> {
  return client.request(`${sourcePath(projectId, sourceId)}/view`, {
    method: 'PUT',
    body: { branch }
  })
}

export function resetSourceView(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<SourceView> {
  return client.request(`${sourcePath(projectId, sourceId)}/view`, { method: 'DELETE' })
}
