// Typed wrappers over the Solus REST endpoints used by onboarding + workspace
// (API.md §2.1/§2.3). Each takes an injectable client (defaults to the app
// singleton) so callers and tests stay decoupled from transport. Field names
// are snake_case to match the backend envelope (API.md §1.4).
import { api, type ApiClient, type Page } from './client'
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

export type OnboardingStepName = 'about' | 'connect' | 'build' | 'done'

export interface UserSettings {
  sol_mode: ApiSolMode
  data_collection_consent: boolean
  onboarding_step: OnboardingStepName | string
}

export function getSettings(client: ApiClient = api): Promise<UserSettings> {
  return client.request<UserSettings>('/users/me/settings')
}

export function updateOnboardingStep(
  step: OnboardingStepName,
  client: ApiClient = api
): Promise<UserSettings> {
  return client.request<UserSettings>('/users/me/settings', {
    method: 'PATCH',
    body: { onboarding_step: step }
  })
}

export function createProject(
  teamId: string,
  input: { name: string; description?: string },
  client: ApiClient = api
): Promise<Project> {
  return client.request<Project>(`/teams/${teamId}/projects`, { method: 'POST', body: input })
}

/** Projects owned by a team (API.md §2.3), newest first per the backend. */
export function listProjects(teamId: string, client: ApiClient = api): Promise<Project[]> {
  return client.request<Project[]>(`/teams/${teamId}/projects`)
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

/* ---------------- Teams (§2.2) — members, invites, activity ---------------- */

export type TeamRole = 'owner' | 'admin' | 'member' | 'viewer'

export interface TeamDetail {
  id: string
  name: string
  is_personal: boolean
  plan_status: string
  settings: { notify_project_created: boolean }
  created_at: string
  member_count: number
  role: TeamRole
}

export interface TeamMemberApi {
  user_id: string
  email: string
  name: string | null
  role: TeamRole
  joined_at: string
}

export type InviteStatus = 'pending' | 'accepted' | 'revoked'

export interface InviteApi {
  id: string
  team_id: string
  email: string
  role: TeamRole
  status: InviteStatus
  created_at: string
  expires_at: string
  /** Secret shown once at creation — never on listings. */
  token?: string
}

export interface ActivityApi {
  id: string
  type: string
  domain: string | null
  actor_id: string | null
  project_id: string | null
  payload: Record<string, unknown>
  created_at: string
}

export interface NotificationApi {
  id: string
  type: string
  title: string
  body: string | null
  payload: Record<string, unknown>
  read_at: string | null
  created_at: string
}

/** Create a team (API.md §2.2 — also the individual→team upgrade entry point). */
export function createTeam(name: string, client: ApiClient = api): Promise<TeamDetail> {
  return client.request<TeamDetail>('/teams', { method: 'POST', body: { name } })
}

export function getTeamDetail(teamId: string, client: ApiClient = api): Promise<TeamDetail> {
  return client.request<TeamDetail>(`/teams/${teamId}`)
}

export function updateTeam(
  teamId: string,
  input: { name?: string; settings?: { notify_project_created: boolean } },
  client: ApiClient = api
): Promise<TeamDetail> {
  return client.request<TeamDetail>(`/teams/${teamId}`, { method: 'PATCH', body: input })
}

/** Delete a team (owner only; API.md §2.2). Irreversible — confirm in the UI first. */
export function deleteTeam(teamId: string, client: ApiClient = api): Promise<void> {
  return client.request<void>(`/teams/${teamId}`, { method: 'DELETE' })
}

export function listMembers(teamId: string, client: ApiClient = api): Promise<TeamMemberApi[]> {
  return client.request<TeamMemberApi[]>(`/teams/${teamId}/members`)
}

export function changeMemberRole(
  teamId: string,
  userId: string,
  role: TeamRole,
  client: ApiClient = api
): Promise<TeamMemberApi> {
  return client.request<TeamMemberApi>(`/teams/${teamId}/members/${userId}`, {
    method: 'PATCH',
    body: { role }
  })
}

export function removeMember(
  teamId: string,
  userId: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' })
}

export function listInvites(teamId: string, client: ApiClient = api): Promise<InviteApi[]> {
  return client.request<InviteApi[]>(`/teams/${teamId}/invites`)
}

export function createInvite(
  teamId: string,
  input: { email: string; role?: Exclude<TeamRole, 'owner'> },
  client: ApiClient = api
): Promise<InviteApi> {
  return client.request<InviteApi>(`/teams/${teamId}/invites`, { method: 'POST', body: input })
}

export function revokeInvite(
  teamId: string,
  inviteId: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`/teams/${teamId}/invites/${inviteId}`, { method: 'DELETE' })
}

export function listActivity(teamId: string, client: ApiClient = api): Promise<ActivityApi[]> {
  return client.request<ActivityApi[]>(`/teams/${teamId}/activity`)
}

/** One cursor page of the team activity feed (§2.2) — carries pagination meta. */
export function listActivityPage(
  teamId: string,
  cursor?: string,
  client: ApiClient = api
): Promise<Page<ActivityApi[]>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return client.requestPage<ActivityApi[]>(`/teams/${teamId}/activity${query}`)
}

/* ---------------- Notifications (§2.1) ---------------- */

export function listNotifications(client: ApiClient = api): Promise<NotificationApi[]> {
  return client.request<NotificationApi[]>('/users/me/notifications')
}

/** One cursor page of the current user's notifications (§2.1) — with meta. */
export function listNotificationsPage(
  cursor?: string,
  client: ApiClient = api
): Promise<Page<NotificationApi[]>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return client.requestPage<NotificationApi[]>(`/users/me/notifications${query}`)
}

export function markNotificationRead(
  id: string,
  client: ApiClient = api
): Promise<NotificationApi> {
  return client.request<NotificationApi>(`/users/me/notifications/${id}/read`, { method: 'POST' })
}
