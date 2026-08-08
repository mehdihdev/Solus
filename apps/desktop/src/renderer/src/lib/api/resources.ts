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
  /** Soft-delete timestamp (SOLUSDEV-84); null when active. */
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface ProjectDetail extends Project {
  stats: { entities: number; relations: number }
  sources: unknown[]
}

export type SourceStatus = 'pending' | 'connected' | 'syncing' | 'error' | 'disconnected'

/** Structured sync/connect failure as the API serializes it (models.Source.last_error). */
export interface SourceError {
  code: string
  message: string
}

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
  last_error: SourceError | null
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

export function apiToSolMode(mode: ApiSolMode): SolMode {
  return mode === 'expert' ? 'Expert' : 'Guide'
}

export function getMe(client: ApiClient = api): Promise<Me> {
  return client.request<Me>('/users/me')
}

/** Permanently delete the caller's account (API.md §1.3, SOLUSDEV-82). Rejects
 * with a 409 `ownership_transfer_required` (blocking team ids in the error
 * details) when the caller is the sole owner of a shared team. */
export function deleteMe(client: ApiClient = api): Promise<void> {
  return client.request<void>('/users/me', { method: 'DELETE' })
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

/** Toggle data-collection consent (ADR-011 opt-in/out). Returns the fresh settings. */
export function updateConsent(consent: boolean, client: ApiClient = api): Promise<UserSettings> {
  return client.request<UserSettings>('/users/me/settings', {
    method: 'PATCH',
    body: { data_collection_consent: consent }
  })
}

/** Update the current user's profile (display name / avatar) — PATCH /users/me. */
export function updateProfile(
  input: { name?: string; avatar_url?: string },
  client: ApiClient = api
): Promise<Me> {
  return client.request<Me>('/users/me', { method: 'PATCH', body: input })
}

export type PlanType = 'basic' | 'pro' | 'enterprise' | string
export type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'canceled' | string

/** Billing summary source (API.md §2.14 / GET /users/me/subscription). No secrets.
 *  `limits` values are `null` when unlimited (models.PLAN_LIMITS). */
export interface Subscription {
  user_id: string
  plan: PlanType
  status: SubscriptionStatus
  limits: Record<string, number | null>
  expires_at: string | null
  /** Pending cancel-at-period-end moment — the plan stays live until then and
   *  the billing page shows a persistent "ends on <date>" bar. */
  cancel_at?: string | null
  seat_count: number | null
  /** Set once the user has a live Stripe subscription — plan changes then go
   *  through the billing portal, not a new Checkout (avoids double-billing). */
  stripe_subscription_id?: string | null
}

/** The current user's live subscription (plan, trial state, seats, plan limits). */
export function getSubscription(client: ApiClient = api): Promise<Subscription> {
  return client.request<Subscription>('/users/me/subscription')
}

/** Pick/change the plan (API.md §2.14 / PATCH /users/me/subscription). No Stripe
 *  call — (re)starts a 14-day trial of the chosen plan with its limits (ADR-032). */
export function updateSubscription(plan: PlanType, client: ApiClient = api): Promise<Subscription> {
  return client.request<Subscription>('/users/me/subscription', {
    method: 'PATCH',
    body: { plan }
  })
}

export type CheckoutInterval = 'month' | 'year'

/** A Stripe-hosted redirect URL (Checkout or billing portal). */
export interface CheckoutSession {
  url: string
}

/** Current credit balance (GET /users/me/credits). */
export interface CreditBalance {
  user_id: string
  balance: number
}

/** A purchasable credit pack (GET /billing/packs) — price id + credits granted.
 *  `usd` is the display price in whole dollars when the server has it mapped;
 *  the charged amount is always the Stripe Price itself. */
export interface CreditPack {
  price_id: string
  credits: number
  usd?: number | null
}

/** Start a Stripe Checkout for a subscription plan → hosted redirect URL
 *  (POST /billing/checkout-session). The plan is applied by the webhook once
 *  Stripe confirms payment, never from this call. */
export function createSubscriptionCheckout(
  plan: PlanType,
  interval: CheckoutInterval,
  client: ApiClient = api
): Promise<CheckoutSession> {
  return client.request<CheckoutSession>('/billing/checkout-session', {
    method: 'POST',
    body: { kind: 'subscription', plan, interval }
  })
}

/** Start a Stripe Checkout for a one-off credit pack → hosted redirect URL. */
export function createPackCheckout(
  priceId: string,
  client: ApiClient = api
): Promise<CheckoutSession> {
  return client.request<CheckoutSession>('/billing/checkout-session', {
    method: 'POST',
    body: { kind: 'pack', price_id: priceId }
  })
}

/** Open the Stripe billing portal (manage payment method / cancel) → URL. */
export function createBillingPortal(client: ApiClient = api): Promise<CheckoutSession> {
  return client.request<CheckoutSession>('/billing/portal-session', { method: 'POST' })
}

/** The current user's credit balance. */
export function getCredits(client: ApiClient = api): Promise<CreditBalance> {
  return client.request<CreditBalance>('/users/me/credits')
}

/** The credit packs available for purchase (server-configured Stripe prices). */
export function getCreditPacks(client: ApiClient = api): Promise<CreditPack[]> {
  return client.request<{ packs: CreditPack[] }>('/billing/packs').then((r) => r.packs)
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

/** Projects owned by a team (API.md §2.3), newest first per the backend.
 *  Pass `includeArchived` to include soft-deleted projects (SOLUSDEV-84). */
export function listProjects(
  teamId: string,
  options: { includeArchived?: boolean } = {},
  client: ApiClient = api
): Promise<Project[]> {
  const query = options.includeArchived ? '?include_archived=true' : ''
  return client.request<Project[]>(`/teams/${teamId}/projects${query}`)
}

export function getProject(projectId: string, client: ApiClient = api): Promise<ProjectDetail> {
  return client.request<ProjectDetail>(`/projects/${projectId}`)
}

/** Rename / re-describe a project (API.md §2.3). Returns the updated detail. */
export function updateProject(
  projectId: string,
  input: { name?: string; description?: string },
  client: ApiClient = api
): Promise<ProjectDetail> {
  return client.request<ProjectDetail>(`/projects/${projectId}`, { method: 'PATCH', body: input })
}

/** Archive (soft-delete) a project — SOLUSDEV-84. Idempotent; returns the project. */
export function archiveProject(projectId: string, client: ApiClient = api): Promise<Project> {
  return client.request<Project>(`/projects/${projectId}/archive`, { method: 'POST' })
}

/** Restore an archived project — SOLUSDEV-84. Idempotent; returns the project. */
export function unarchiveProject(projectId: string, client: ApiClient = api): Promise<Project> {
  return client.request<Project>(`/projects/${projectId}/unarchive`, { method: 'POST' })
}

/** Permanently delete a project (admin, confirmation required — API.md §2.3). */
export function deleteProject(projectId: string, client: ApiClient = api): Promise<void> {
  return client.request<void>(`/projects/${projectId}`, { method: 'DELETE' })
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

/** Connect a source directly (non-OAuth providers, e.g. committed-export EDA). */
export function createSource(
  projectId: string,
  input: { type: string; name: string; config?: Record<string, unknown> },
  client: ApiClient = api
): Promise<Source> {
  return client.request<Source>(`/projects/${projectId}/sources`, {
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

/**
 * Disconnect a source from a project (API.md §2.5 — DELETE source). By default
 * the source's already-synced graph data is RETAINED: entities/relations it
 * produced are orphaned into manual, user-owned nodes rather than deleted, so
 * disconnecting never destroys graph history. Pass `retainEntities: false` to
 * also remove that data. The source row is removed either way (reconnectable).
 */
export function disconnectSource(
  projectId: string,
  sourceId: string,
  options: { retainEntities?: boolean } = {},
  client: ApiClient = api
): Promise<{ id: string; retained_entities: boolean }> {
  const retain = options.retainEntities ?? true
  return client.request<{ id: string; retained_entities: boolean }>(
    `/projects/${projectId}/sources/${sourceId}?retain_entities=${retain}`,
    { method: 'DELETE' }
  )
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

export interface AcceptInviteResult {
  team_id: string
  role: TeamRole
}

/** Redeem a one-time invite token (API.md §2.2). Authed as the invitee; the
 *  backend enforces the email match. Returns the joined team + granted role. */
export function acceptInvite(token: string, client: ApiClient = api): Promise<AcceptInviteResult> {
  // Token is user-pasted free text (not a server-issued id) — encode it so a
  // stray `/`, `?`, or `..` can't alter the request path (CLAUDE.md §7).
  return client.request<AcceptInviteResult>(`/invites/${encodeURIComponent(token)}/accept`, {
    method: 'POST'
  })
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

/** Mark every unread notification read (API.md §2.1). Returns the count updated. */
export function markAllNotificationsRead(client: ApiClient = api): Promise<{ updated: number }> {
  return client.request<{ updated: number }>('/users/me/notifications/read-all', { method: 'POST' })
}

// --- Local bridge status (SOLUSDEV-154 / BRG-03) ------------------------------

export type BridgeServerState = 'not_launched' | 'launching' | 'ready' | 'busy' | 'error'

/** MCP-05 BYO-license surface (bridge.py `_license_states`): `ready` (free
 *  tier, uncataloged, or fully licensed) · `bring_your_license` (byo_paid,
 *  entitled, keys missing) · `upgrade_required` (byo_paid, not entitled). */
export type BridgeLicenseState = 'ready' | 'bring_your_license' | 'upgrade_required'

/** One vendored MCP server as last reported by the local companion. */
export interface BridgeServer {
  name: string
  state: BridgeServerState
  detail: string | null
  updated_at: string
  /** Sent for every server on the connected bridge-status surface
   *  (SOLUSDEV-102 / MCP-05); optional for pre-MCP-05 fixtures. */
  license_state?: BridgeLicenseState
}

/** The requesting user's local-bridge state for a project. Offline shape is
 *  `{connected: false, companion_version: null, servers: []}`. */
export interface BridgeStatus {
  connected: boolean
  companion_version: string | null
  connected_at?: string
  status_updated_at?: string | null
  servers: BridgeServer[]
}

export function getBridgeStatus(projectId: string, client: ApiClient = api): Promise<BridgeStatus> {
  return client.request<BridgeStatus>(`/projects/${projectId}/bridge`)
}

// --- MO-04: pre-flight classification preview --------------------------------

export type CostTier = 'low' | 'standard' | 'premium'
// Closed sets mirroring the backend enums (orchestration/enums.py) and the
// resolution Source literal — compile-time protection at the request boundary.
export type ComplexityValue = 'trivial' | 'standard' | 'hard'
export type RouteTypeValue = 'general' | 'code' | 'visual_log' | 'long_context'
export type ClassifySource = 'explicit' | 'context' | 'estimator'

export interface ClassifyOption<V extends string = string> {
  value: V
  viable: boolean
  /** Short factual note when not viable, e.g. "Too many tokens for this tier (340K > 200K)". */
  reason: string | null
  model: string
  cost_tier: CostTier
}

export interface ClassifyPreview {
  complexity: ComplexityValue
  type: RouteTypeValue
  model: { name: string; provider: string }
  cost_tier: CostTier
  source: { complexity: ClassifySource; type: ClassifySource }
  tokens_estimate: number
  viable: boolean
  reason: string | null
  escalated: boolean
  options: {
    complexities: ClassifyOption<ComplexityValue>[]
    types: ClassifyOption<RouteTypeValue>[]
  }
}

export interface ClassifyRequestBody {
  query: string
  complexity?: ComplexityValue
  type?: RouteTypeValue
}

/** Routing preview — no model call, no credits, its own generous rate bucket. */
export function classifyQuery(
  body: ClassifyRequestBody,
  client: ApiClient = api
): Promise<ClassifyPreview> {
  return client.request<ClassifyPreview>('/orchestration/classify', { method: 'POST', body })
}
