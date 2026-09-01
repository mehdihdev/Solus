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

/** A graph edge between two entities. Public keys mirror `serialize_relation` (API.md §2.4). */
export interface Relation {
  id: string
  type: string
  from_entity_id: string
  to_entity_id: string
}

/**
 * The induced subgraph around a focused entity (API.md §2.4 `GET /projects/{id}/graph`).
 *
 * Every edge has BOTH endpoints in `entities`, so a widget can render it without guarding against
 * dangling references. `truncated` is `true` when the server's entity cap bit — surface it, since
 * a silently capped neighbourhood reads as the whole picture.
 */
export interface Neighborhood {
  entities: Entity[]
  edges: Relation[]
  truncated: boolean
}

/** Options for a neighbourhood read. `depth` is capped at 2 server-side. */
export interface NeighborhoodOptions {
  depth?: number
  entity_types?: string[]
  relation_types?: string[]
  limit?: number
}

/** The focus-scope read: one bounded call re-scopes every mounted widget (WS-01). */
export function getGraphNeighborhood(
  projectId: string,
  root: string,
  options: NeighborhoodOptions = {},
  client: ApiClient = api
): Promise<Neighborhood> {
  const params = new URLSearchParams({ root, depth: String(options.depth ?? 1) })
  if (options.entity_types?.length) params.set('entity_types', options.entity_types.join(','))
  if (options.relation_types?.length) params.set('relation_types', options.relation_types.join(','))
  if (options.limit) params.set('limit', String(options.limit))
  return client.request<Neighborhood>(`/projects/${projectId}/graph?${params.toString()}`)
}

/** A repository discoverable through a connected GitHub source. */
export interface GithubRepo {
  full_name: string
  default_branch: string
  private: boolean
}

/** One thing a connected source can be pointed at: a repository, a CAD
 *  document, … . `config` (when present) is the exact source config choosing
 *  this item writes, so the app never has to know what the item means. */
export interface SelectableItem {
  id: string
  name: string
  subtitle?: string
  config?: Record<string, unknown>
}

/** How a connector lets a user choose what to track, from the live registry. */
export interface IntegrationSelection {
  mode: 'single' | 'multi'
  config_key: string
  label: string
}

/** One grant a connector offers at connect time. */
export interface IntegrationAccessMode {
  id: string
  label: string
  description: string
  scopes: readonly string[]
}

/** How much power the user grants while connecting, from the live registry.
 *  Null when the provider offers no choice. */
export interface IntegrationAccessModes {
  default: string
  modes: readonly IntegrationAccessMode[]
}

/** The integration catalog entry (auth + config requirements). */
export interface Integration {
  type: string
  auth_kind: string
  config_fields: string[]
  scopes: string[]
  /** Null when the connector has nothing to pick after connecting. */
  selection?: IntegrationSelection | null
  access_modes?: IntegrationAccessModes | null
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
  /** Standing preference note for SOL (SOLUSDEV-233); null when unset. */
  sol_custom_instruction: string | null
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

/** Set (string) or clear (null) the SOL custom instruction (SOLUSDEV-233). */
export function updateCustomInstruction(
  instruction: string | null,
  client: ApiClient = api
): Promise<UserSettings> {
  return client.request<UserSettings>('/users/me/settings', {
    method: 'PATCH',
    body: { sol_custom_instruction: instruction }
  })
}

/** GET /users/me/usage (SOLUSDEV-233): the ADR-018 always-visible meter,
 *  credit-denominated. `allowance` null = no plan-derived denominator. */
export interface UsageApi {
  used: number
  allowance: number | null
  balance: number
  cycle_start: string
  cycle_end: string
}

export function getUsage(client: ApiClient = api): Promise<UsageApi> {
  return client.request<UsageApi>('/users/me/usage')
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

/** What a connected source can be pointed at (repositories, CAD documents, …).
 *  One generic route for every connector. */
export function listSelectable(
  projectId: string,
  sourceId: string,
  client: ApiClient = api
): Promise<SelectableItem[]> {
  return client.request<SelectableItem[]>(`/projects/${projectId}/sources/${sourceId}/selectable`)
}

/**
 * Begin a loopback OAuth flow for `provider`; returns the authorize URL + state.
 * The provider is an argument, never baked into the path — the backend routes
 * are `/{provider}/oauth/*`, so every OAuth connector the registry grows is
 * reachable without a change here.
 */
export function startOAuth(
  projectId: string,
  provider: string,
  input: { redirect_uri?: string; name?: string; access?: string } = {},
  client: ApiClient = api
): Promise<OAuthStartResponse> {
  return client.request<OAuthStartResponse>(`/integrations/${provider}/oauth/start`, {
    method: 'POST',
    body: { project_id: projectId, ...input }
  })
}

/** Exchange the OAuth state + code for a connected source. */
export function exchangeOAuth(
  provider: string,
  input: { state: string; code: string },
  client: ApiClient = api
): Promise<Source> {
  return client.request<Source>(`/integrations/${provider}/oauth/exchange`, {
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

/**
 * Every entity in the project. The server pages this route (default 200, cap
 * 500) and `client.request` discards the envelope's `meta`, so a single call
 * silently truncates any project past one page — this walks the cursor to the
 * end instead.
 */
// ponytail: sequential cursor walk; the canvas ticket owns search/virtualization when projects hit many thousands
export async function listAllEntities(
  projectId: string,
  client: ApiClient = api
): Promise<Entity[]> {
  const all: Entity[] = []
  let cursor: string | null = null
  do {
    const params = new URLSearchParams({ limit: '500' })
    if (cursor) params.set('cursor', cursor)
    const page = await client.requestPage<Entity[]>(
      `/projects/${projectId}/entities?${params.toString()}`
    )
    all.push(...page.data)
    cursor = page.meta.has_next ? (page.meta.next_cursor ?? null) : null
  } while (cursor)
  return all
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

export interface ActivityPageOptions {
  cursor?: string
  /** Server caps at 100 (API.md §2.2); defaults to 50 when omitted. */
  limit?: number
}

/** One cursor page of the team activity feed (§2.2) — carries pagination meta
 *  including `total`, the filter-matching row count across the whole feed. */
export function listActivityPage(
  teamId: string,
  options: ActivityPageOptions = {},
  client: ApiClient = api
): Promise<Page<ActivityApi[]>> {
  const params = new URLSearchParams()
  if (options.cursor) params.set('cursor', options.cursor)
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  const query = params.toString()
  // teamId is server-issued today; encoded anyway so it can never alter the path.
  return client.requestPage<ActivityApi[]>(
    `/teams/${encodeURIComponent(teamId)}/activity${query ? `?${query}` : ''}`
  )
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
  /** MCP-05 BYO-licence readiness, computed server-side and previously
   *  discarded by this client. A tool can be CONNECTED but not usable — a
   *  paid-tier server with no customer licence reports its state here, and
   *  showing "connected" alone would misrepresent that. Optional because a
   *  free-tier server (Fusion) simply reports "ready", and for pre-MCP-05
   *  fixtures. */
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

// --- SOL (SOLUSDEV-96 / ONS-UI-01) ---------------------------------------
// `createSolConversation` used to live here too. The SOLUSDEV-68 merge brought
// LANE C's `features/sol/solApi.ts`, which defines the same POST against the
// same endpoint, and that is the copy every production caller now uses — so the
// one here was dead. Removed rather than left as a second definition nobody
// could tell apart. The remaining SOL calls below still live here because
// nothing in features/sol owns them yet; consolidating the two layers is a
// separate call.

/**
 * Approve or reject a destructive action SOL parked.
 *
 * A decision and NOTHING ELSE — the arguments that execute are the ones the
 * server stored and showed the user. Sending args here would defeat the point,
 * and the API rejects a body that carries them.
 */
export interface ConfirmationOutcome {
  /** False when nothing ran: expired, already decided, the tool is gone, the
   *  described effect changed, or the tool itself failed. A REJECTION is also
   *  ok:false — refusing to run is its success — so callers must branch on the
   *  decision, not on this flag alone. */
  readonly ok?: boolean
  readonly error?: { readonly code?: string; readonly message?: string }
}

export function decideSolConfirmation(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject',
  client: ApiClient = api
): Promise<ConfirmationOutcome> {
  return client.request<ConfirmationOutcome>(
    `/projects/${projectId}/sol/confirmations/${confirmationId}`,
    { method: 'POST', body: { decision } }
  )
}

// --- Onshape panel links (SOLUS-A7-01) ------------------------------------
// A panel link is a SECOND credential class: a long-lived token the Onshape
// in-app panel holds, minted only after the signed-in user approves the code
// the panel is showing. The desktop app never sees that token — it only
// approves the pairing and can revoke it afterwards.

export interface PanelLink {
  id: string
  /** Untrusted label from Onshape, shown only so two links are tellable apart. */
  onshape_user_id: string | null
  created_at: string
  last_used_at: string | null
  expires_at: string
}

export function listPanelLinks(client: ApiClient = api): Promise<PanelLink[]> {
  return client.request<PanelLink[]>('/users/me/panel-links')
}

/** Approve the code the panel is displaying. Rejects 404 `invalid_pairing`
 * (wrong or expired) and 409 `already_approved`. */
export function approvePanelLink(
  userCode: string,
  client: ApiClient = api
): Promise<{ status: string }> {
  return client.request<{ status: string }>('/users/me/panel-links', {
    method: 'POST',
    body: { user_code: userCode }
  })
}

export function revokePanelLink(linkId: string, client: ApiClient = api): Promise<void> {
  return client.request<void>(`/users/me/panel-links/${linkId}`, { method: 'DELETE' })
}

// --- Local connections: bench sources + sessions (SOLUSDEV-72) --------------

/** Whether livebench is installed server-side. `available=false` disables every
 *  simulator/device control, explained by `reason` — never silently. */
export interface BenchRunner {
  available: boolean
  reason: string | null
}

export type BenchSimulatorKind = 'mujoco' | 'gazebo' | 'isaac' | 'mcap-replay'

export interface BenchSimulator {
  kind: BenchSimulatorKind
  available: boolean
  reason: string | null
}

/** A serial device as the backend detected it. Everything here is a CLAIM the
 *  UI must render verbatim — a `usb_bridge` board class means the MCU behind
 *  the bridge is unknown, and the UI must never guess a board for it. */
export interface BenchDevice {
  device_path: string
  by_id_path: string | null
  serial_number: string | null
  vid: string
  pid: string
  board: string | null
  board_class: string
  mcu_known: boolean
  confidence: number
  /** Two+ devices share a serial or lack one — connect requires an explicit
   *  user pick of the device_path (propose, never assert). */
  ambiguous: boolean
  note: string | null
}

export interface BenchSources {
  runner: BenchRunner
  simulators: BenchSimulator[]
  devices: BenchDevice[]
}

export function getBenchSources(projectId: string, client: ApiClient = api): Promise<BenchSources> {
  return client.request<BenchSources>(`/projects/${projectId}/bench/sources`)
}

export interface MujocoSimConfig {
  provider: 'mujoco'
  /** Omit mjcf_xml → the builtin demo scene. */
  scene_name?: string
  mjcf_xml?: string
  sample_hz?: number
  duration_seconds?: number
  window_seconds?: number
}

export interface GazeboSimConfig {
  provider: 'gazebo'
  topics: string[]
}

export interface McapReplayConfig {
  provider: 'mcap-replay'
  /** Path under the server's bench data root — never a client filesystem path. */
  mcap_path: string
  topics?: string[]
}

/** ALWAYS send serial_number when the device has one; confirmed_device_path is
 *  ONLY for a user-confirmed pick of a serial-less/ambiguous device. */
export interface SerialRealConfig {
  provider: 'serial'
  serial_number?: string
  confirmed_device_path?: string
  baud?: number
}

export type CreateBenchSessionInput =
  | { mode: 'sim'; config: MujocoSimConfig | GazeboSimConfig | McapReplayConfig }
  | { mode: 'real'; config: SerialRealConfig }

export type BenchSessionStatus = 'starting' | 'active' | 'ended'
/** Honest live link state — a dead pump reads `disconnected`, never "streaming". */
export type BenchLinkState = 'disconnected' | 'connected' | 'streaming'

export interface BenchWindowSummary {
  window_start: string
  window_end: string
  summary: string
  signals: Record<string, unknown>
  anomalies: unknown
}

/** The device echo on a real session — NOT a full BenchDevice. `device_path`
 *  is set only when the session was started from an explicit user pick. */
export interface BenchSessionDevice {
  serial_number: string | null
  device_path: string | null
  baud: number
}

export interface BenchSession {
  id: string
  mode: 'sim' | 'real'
  provider: string
  status: BenchSessionStatus
  link: BenchLinkState
  label: string
  created_at: string
  ended_at: string | null
  device: BenchSessionDevice | null
  device_ids: string[]
  counts: { ingested: number; unresolved: number }
  last_summary: BenchWindowSummary | null
}

/** Start a bench session. Errors worth branching on (ApiError.code):
 *  409 `too_many_sessions`, 409 `device_ambiguous` (candidates in details),
 *  503 `source_unavailable`, 422 validation. */
export function createBenchSession(
  projectId: string,
  input: CreateBenchSessionInput,
  client: ApiClient = api
): Promise<BenchSession> {
  return client.request<BenchSession>(`/projects/${projectId}/bench/sessions`, {
    method: 'POST',
    body: input
  })
}

export function listBenchSessions(
  projectId: string,
  filters: { status?: BenchSessionStatus; mode?: 'sim' | 'real' } = {},
  client: ApiClient = api
): Promise<BenchSession[]> {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.mode) params.set('mode', filters.mode)
  const query = params.toString()
  return client.request<BenchSession[]>(
    `/projects/${projectId}/bench/sessions${query ? `?${query}` : ''}`
  )
}

export function getBenchSession(
  projectId: string,
  sessionId: string,
  client: ApiClient = api
): Promise<BenchSession> {
  return client.request<BenchSession>(`/projects/${projectId}/bench/sessions/${sessionId}`)
}

/** Stop a session. Idempotent — stopping an ended session is not an error. */
export function stopBenchSession(
  projectId: string,
  sessionId: string,
  client: ApiClient = api
): Promise<BenchSession> {
  return client.request<BenchSession>(`/projects/${projectId}/bench/sessions/${sessionId}/stop`, {
    method: 'POST'
  })
}

export interface BenchSignalPoint {
  timestamp: string
  value: number
}

export interface BenchSignalSeries {
  signal: string
  points: BenchSignalPoint[]
}

/** Recent telemetry for a DEVICE (serves devices with no graph entity;
 *  `resolved_entity_id` non-null means the entity view also works). */
export interface BenchDeviceRecent {
  device_id: string
  resolved_entity_id: string | null
  signals: BenchSignalSeries[]
}

/** Batched read: 1..16 repeated `device_id` params, one entry per requested
 *  id in the same order. One call per poll cycle — never one per device. */
export function getBenchDeviceRecent(
  projectId: string,
  deviceIds: readonly string[],
  options: { limit?: number } = {},
  client: ApiClient = api
): Promise<BenchDeviceRecent[]> {
  const params = new URLSearchParams()
  for (const deviceId of deviceIds) params.append('device_id', deviceId)
  if (options.limit) params.set('limit', String(options.limit))
  return client
    .request<{
      devices: BenchDeviceRecent[]
    }>(`/projects/${projectId}/bench/device-recent?${params.toString()}`)
    .then((r) => r.devices)
}

/** A vendor-run local tool reachable through the companion bridge (no project
 *  scope). Copy fields are shown verbatim — honest guidance, never invented. */
export interface LocalTool {
  type: string
  display_name: string
  hosting: string
  url_host: string
  connect_notice: string
  requires: string
}

export function listLocalTools(client: ApiClient = api): Promise<LocalTool[]> {
  return client.request<LocalTool[]>('/integrations/local-tools')
}
