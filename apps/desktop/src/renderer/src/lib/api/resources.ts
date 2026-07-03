// Typed wrappers over the Solus REST endpoints used by onboarding + workspace
// (API.md §2.1/§2.3). Each takes an injectable client (defaults to the app
// singleton) so callers and tests stay decoupled from transport. Field names
// are snake_case to match the backend envelope (API.md §1.4).
import { api, type ApiClient } from './client'
import type { SolMode } from '../../store/settingsStore'

export interface TeamSummary {
  team_id: string
  name: string
  role: string
  is_personal: boolean
  plan_status: string
  trial_ends_at: string
}

export interface Me {
  id: string
  email: string
  name: string | null
  avatar_url: string | null
  created_at: string
  teams: TeamSummary[]
}

export interface Project {
  id: string
  team_id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface ProjectDetail extends Project {
  stats: { entities: number; relations: number }
  sources: unknown[]
}

export type SourceStatus = 'pending' | 'connected' | 'syncing' | 'error' | 'disconnected'

/** A connected external tool feeding the graph. Secrets are NEVER present. */
export interface Source {
  id: string
  project_id: string
  type: string
  name: string
  status: SourceStatus
  config: Record<string, unknown>
  account_login: string | null
  last_synced_at: string | null
  last_error: string | null
  entity_count?: number
  created_at: string
  updated_at: string
}

export type SyncStatus = 'queued' | 'running' | 'succeeded' | 'failed'

/** A sync run for a source (API.md §2.5). */
export interface Sync {
  id: string
  status: SyncStatus
  entities_created: number
  relations_created: number
  errors: unknown[]
}

/** A graph entity extracted from a source. */
export interface Entity {
  id: string
  type: string
  domain: string
  name: string
  source_key: string
}

/** A repository discoverable through a connected GitHub source. */
export interface GithubRepo {
  full_name: string
  default_branch: string
  private: boolean
}

/** The integration catalog entry (auth + config requirements). */
export interface Integration {
  type: string
  auth_kind: string
  config_fields: string[]
  scopes: string[]
}

/** Response from kicking off the GitHub loopback OAuth flow. */
export interface OAuthStartResponse {
  authorize_url: string
  state: string
  source_id: string
}

export type ApiSolMode = 'guide' | 'expert'

export function solModeToApi(mode: SolMode): ApiSolMode {
  return mode === 'Expert' ? 'expert' : 'guide'
}

export function getMe(client: ApiClient = api): Promise<Me> {
  return client.request<Me>('/users/me')
}

export function updateSolMode(mode: SolMode, client: ApiClient = api): Promise<unknown> {
  return client.request('/users/me/settings', {
    method: 'PATCH',
    body: { sol_mode: solModeToApi(mode) }
  })
}

export function createProject(
  teamId: string,
  input: { name: string; description?: string },
  client: ApiClient = api
): Promise<Project> {
  return client.request<Project>(`/teams/${teamId}/projects`, { method: 'POST', body: input })
}

export function getProject(projectId: string, client: ApiClient = api): Promise<ProjectDetail> {
  return client.request<ProjectDetail>(`/projects/${projectId}`)
}

/** The personal team auto-provisioned at first login (API.md §1.3). */
export function personalTeam(me: Me): TeamSummary | undefined {
  return me.teams.find((t) => t.is_personal) ?? me.teams[0]
}

// --- Integrations + sources (API.md §2.5) ---------------------------------

/** The connector catalog (auth + config requirements per type). */
export function listIntegrations(client: ApiClient = api): Promise<Integration[]> {
  return client.request<Integration[]>('/integrations')
}

/** Sources connected to a project. */
export function listSources(projectId: string, client: ApiClient = api): Promise<Source[]> {
  return client.request<Source[]>(`/projects/${projectId}/sources`)
}

/** A single source (used to read entity_count after a sync). */
export function getSource(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<Source> {
  return client.request<Source>(`/projects/${projectId}/sources/${sourceId}`)
}

/** Repositories reachable through a connected GitHub source. */
export function listRepos(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<GithubRepo[]> {
  return client.request<GithubRepo[]>(`/projects/${projectId}/sources/${sourceId}/repos`)
}

/** Begin the GitHub loopback OAuth flow; returns the authorize URL + state. */
export function startGithubOAuth(
  projectId: string,
  input: { redirect_uri?: string; repo?: string; name?: string } = {},
  client: ApiClient = api
): Promise<OAuthStartResponse> {
  return client.request<OAuthStartResponse>('/integrations/github/oauth/start', {
    method: 'POST',
    body: { project_id: projectId, ...input }
  })
}

/** Exchange the OAuth state + code for a connected source. */
export function exchangeGithubOAuth(
  input: { state: string; code: string },
  client: ApiClient = api
): Promise<Source> {
  return client.request<Source>('/integrations/github/oauth/exchange', {
    method: 'POST',
    body: input
  })
}

/** Update a source's name and/or config (e.g. select the repo + branch). */
export function updateSource(
  projectId: string,
  sourceId: string,
  input: { name?: string; config?: Record<string, unknown> },
  client: ApiClient = api
): Promise<Source> {
  return client.request<Source>(`/projects/${projectId}/sources/${sourceId}`, {
    method: 'PATCH',
    body: input
  })
}

/** Queue a sync for a source. Returns the accepted job descriptor. */
export function triggerSync(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<{ job_id: string; status: string }> {
  return client.request<{ job_id: string; status: string }>(
    `/projects/${projectId}/sources/${sourceId}/sync`,
    { method: 'POST' }
  )
}

/** The sync history for a source, newest-relevant first per the backend. */
export function getSyncs(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<Sync[]> {
  return client.request<Sync[]>(`/projects/${projectId}/sources/${sourceId}/syncs`)
}

/** Graph entities, optionally filtered by type and/or source. */
export function listEntities(
  projectId: string,
  filters: { type?: string; source_id?: string } = {},
  client: ApiClient = api
): Promise<Entity[]> {
  const params = new URLSearchParams()
  if (filters.type) params.set('type', filters.type)
  if (filters.source_id) params.set('source_id', filters.source_id)
  const query = params.toString()
  return client.request<Entity[]>(`/projects/${projectId}/entities${query ? `?${query}` : ''}`)
}
