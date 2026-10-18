// SOLUSDEV-216: typed client for docs/api/github-orgs.md — a team-owned GitHub
// App installation (ADR-039). Wire shapes are snake_case as the API sends them.
// No token ever crosses this module: the API mints installation tokens itself.
import { api, type ApiClient } from './client'
import { ApiError } from './envelope.types'
import type { SelectableItem } from './resources'

/** `TeamInstallationRead` (docs/api/github-orgs.md §2). */
export interface TeamInstallation {
  id: string
  provider: 'github'
  account_login: string
  account_type: 'Organization' | 'User'
  account_avatar_url: string | null
  repository_selection: 'all' | 'selected'
  status: 'active' | 'suspended'
  linked_by: { user_id: string; name: string | null } | null
  linked_at: string
  /** https://github.com/<login> */
  html_url: string
  /** GitHub page to change repo access or uninstall. */
  manage_url: string
  /** Live project sources reading through it; the unlink confirm names it. */
  bound_source_count?: number
}

export type SolusMemberStatus = 'member' | 'invited' | 'not_on_solus'

export interface GithubOrgMember {
  github_id: number
  github_login: string
  avatar_url: string
  solus_status: SolusMemberStatus
}

export interface GithubInstallStart {
  install_url: string
  state: string
  redirect_uri: string
}

export type GithubSetupAction = 'install' | 'update' | 'request'

export interface GithubInstallCompleteInput {
  state: string
  /** GitHub may omit it on an owner-approval `request` redirect. */
  code?: string
  /** Absent when `setup_action` is `request` (an owner has not approved yet). */
  installation_id?: number
  setup_action: GithubSetupAction
}

/** 201 linked, or 202 `requested` (a non-owner asked an org owner to approve). */
export type GithubInstallResult =
  | { kind: 'linked'; installation: TeamInstallation }
  | { kind: 'requested' }

export interface GithubUnlinkResult {
  disabled_sources: number
  manage_url: string
}

export interface GithubListOptions {
  cursor?: string
  limit?: number
}

export interface GithubReposPage {
  items: SelectableItem[]
  total: number | null
  cursor: string | null
}

export interface GithubMembersPage {
  items: GithubOrgMember[]
  total: number | null
  cursor: string | null
}

/** Every code docs/api/github-orgs.md documents for this feature. */
export const GITHUB_ORG_ERROR_CODES = [
  'personal_team_unsupported',
  'already_linked',
  'installation_linked_elsewhere',
  'installation_not_accessible',
  'installation_admin_required',
  'install_state_invalid',
  'plan_limit_reached',
  'github_app_unconfigured',
  'installation_suspended',
  'installation_revoked',
  'installation_missing',
  'not_an_organization',
  'not_an_org_member',
  'github_identity_mismatch',
  'repo_not_in_installation',
  'credential_conflict'
] as const

export type GithubOrgErrorCode = (typeof GITHUB_ORG_ERROR_CODES)[number]

const KNOWN_CODES: ReadonlySet<string> = new Set(GITHUB_ORG_ERROR_CODES)

/** The documented GitHub-org code on an error, or null for anything else. */
export function githubOrgErrorCode(error: unknown): GithubOrgErrorCode | null {
  if (!(error instanceof ApiError) || !KNOWN_CODES.has(error.code)) return null
  return error.code as GithubOrgErrorCode
}

const base = (teamId: string): string => `/teams/${encodeURIComponent(teamId)}/github`

function listQuery(options: GithubListOptions & { q?: string }): string {
  const params = new URLSearchParams()
  if (options.cursor) params.set('cursor', options.cursor)
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.q) params.set('q', options.q)
  return params.size ? `?${params}` : ''
}

/** Mint the single-use install state and the GitHub install URL (admin+). */
export function startGithubInstall(
  teamId: string,
  redirectUri?: string,
  client: ApiClient = api
): Promise<GithubInstallStart> {
  return client.request<GithubInstallStart>(`${base(teamId)}/install/start`, {
    method: 'POST',
    body: redirectUri ? { redirect_uri: redirectUri } : {}
  })
}

/** Finish the install with what the loopback captured. A `request` redirect
 *  binds nothing and answers 202 `{status: "requested"}`. */
export async function completeGithubInstall(
  teamId: string,
  input: GithubInstallCompleteInput,
  client: ApiClient = api
): Promise<GithubInstallResult> {
  const data = await client.request<{ installation: TeamInstallation } | { status: 'requested' }>(
    `${base(teamId)}/install/complete`,
    { method: 'POST', body: input }
  )
  if ('installation' in data) return { kind: 'linked', installation: data.installation }
  return { kind: 'requested' }
}

/** The team's live installation, or null (also null on a personal team). */
export async function getTeamInstallation(
  teamId: string,
  client: ApiClient = api
): Promise<TeamInstallation | null> {
  const data = await client.request<{ installation: TeamInstallation | null }>(
    `${base(teamId)}/installation`
  )
  return data.installation
}

/** Unlink (admin+): disables bound sources; GitHub-side uninstall is on manage_url. */
export function unlinkTeamInstallation(
  teamId: string,
  client: ApiClient = api
): Promise<GithubUnlinkResult> {
  return client.request<GithubUnlinkResult>(`${base(teamId)}/installation`, {
    method: 'DELETE'
  })
}

/** Repositories the installation can see, in the OAuth picker's item shape. */
export async function listTeamGithubRepos(
  teamId: string,
  options: GithubListOptions & { q?: string } = {},
  client: ApiClient = api
): Promise<GithubReposPage> {
  const page = await client.requestPage<SelectableItem[]>(
    `${base(teamId)}/repos${listQuery(options)}`
  )
  return { items: page.data, total: page.meta.total ?? null, cursor: page.meta.next_cursor ?? null }
}

/** Org roster (admin+, organizations only) with each login's Solus status. */
export async function listTeamGithubMembers(
  teamId: string,
  options: GithubListOptions = {},
  client: ApiClient = api
): Promise<GithubMembersPage> {
  const page = await client.requestPage<GithubOrgMember[]>(
    `${base(teamId)}/members${listQuery(options)}`
  )
  return { items: page.data, total: page.meta.total ?? null, cursor: page.meta.next_cursor ?? null }
}
