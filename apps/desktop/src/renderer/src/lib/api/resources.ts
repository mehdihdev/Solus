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
