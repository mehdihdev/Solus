import { describe, it, expect, vi } from 'vitest'
import {
  getMe,
  deleteMe,
  updateSolMode,
  createProject,
  getProject,
  solModeToApi,
  personalTeam,
  listIntegrations,
  listSources,
  getSource,
  listSelectable,
  startOAuth,
  exchangeOAuth,
  adoptConnections,
  listConnections,
  listLegacyConnections,
  revokeConnection,
  listConnectionDocuments,
  addSourceDocument,
  removeSourceDocument,
  createSource,
  updateSource,
  disconnectSource,
  triggerSync,
  getSyncs,
  getJob,
  listEntities,
  getGraphNeighborhood,
  type Me
} from './resources'
import type { ApiClient } from './client'

function stubClient(result: unknown): {
  client: ApiClient
  calls: { path: string; options?: unknown }[]
} {
  const calls: { path: string; options?: unknown }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return result as never
    }),
    requestPage: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return { data: result, meta: {} } as never
    })
  }
  return { client, calls }
}

describe('solModeToApi', () => {
  it('maps the UI labels to the API enum', () => {
    expect(solModeToApi('Guide')).toBe('guide')
    expect(solModeToApi('Expert')).toBe('expert')
  })
})

describe('apiToSolMode', () => {
  it('maps the API enum back to the UI labels', async () => {
    const { apiToSolMode } = await import('./resources')
    expect(apiToSolMode('guide')).toBe('Guide')
    expect(apiToSolMode('expert')).toBe('Expert')
  })
})

describe('resource calls', () => {
  it('getMe hits /users/me', async () => {
    const { client, calls } = stubClient({ id: 'u1', teams: [] })
    await getMe(client)
    expect(calls[0].path).toBe('/users/me')
  })

  it('deleteMe DELETEs /users/me', async () => {
    const { client, calls } = stubClient(undefined)
    await deleteMe(client)
    expect(calls[0].path).toBe('/users/me')
    expect((calls[0].options as { method?: string }).method).toBe('DELETE')
  })

  it('updateSolMode PATCHes settings with the mapped enum', async () => {
    const { client, calls } = stubClient({})
    await updateSolMode('Expert', client)
    expect(calls[0].path).toBe('/users/me/settings')
    expect(calls[0].options).toMatchObject({ method: 'PATCH', body: { sol_mode: 'expert' } })
  })

  it('createProject POSTs under the team', async () => {
    const { client, calls } = stubClient({ id: 'p1' })
    await createProject('team-1', { name: 'Strider', description: 'a quadruped' }, client)
    expect(calls[0].path).toBe('/teams/team-1/projects')
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { name: 'Strider', description: 'a quadruped' }
    })
  })

  it('getProject hits the project detail route', async () => {
    const { client, calls } = stubClient({ id: 'p1', stats: { entities: 0, relations: 0 } })
    await getProject('p1', client)
    expect(calls[0].path).toBe('/projects/p1')
  })
})

describe('integration + source calls', () => {
  sourceApiRoutesTests()
  graphApiQueriesTests()
})

// The bug this generalisation exists to prevent: the provider must reach the
// request path, not be baked in. A provider the app has never heard of must
// route to its own OAuth endpoints with no code change here.
describe('OAuth routes are provider-driven', () => {
  it('startOAuth POSTs project_id plus the redirect uri', async () => {
    const { client, calls } = stubClient({ authorize_url: 'u', state: 'st', source_id: 's1' })
    await startOAuth('p1', 'github', { redirect_uri: 'http://127.0.0.1:9/cb' }, client)
    expect(calls[0].path).toBe('/integrations/github/oauth/start')
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { project_id: 'p1', redirect_uri: 'http://127.0.0.1:9/cb' }
    })
  })

  it('startOAuth omits project_id for an ACCOUNT-scoped handshake (SOLUSDEV-241)', async () => {
    const { client, calls } = stubClient({
      authorize_url: 'u',
      state: 'st',
      connection_id: 'c1',
      source_id: null
    })
    await startOAuth(null, 'onshape', { access: 'read' }, client)
    expect(calls[0].options).toMatchObject({ method: 'POST', body: { access: 'read' } })
    expect((calls[0].options as { body: Record<string, unknown> }).body).not.toHaveProperty(
      'project_id'
    )
  })

  it('exchangeOAuth POSTs the state + code', async () => {
    const { client, calls } = stubClient({ connection: { id: 'c1' }, source: null })
    await exchangeOAuth('github', { state: 'st', code: 'cd' }, client)
    expect(calls[0].path).toBe('/integrations/github/oauth/exchange')
    expect(calls[0].options).toMatchObject({ method: 'POST', body: { state: 'st', code: 'cd' } })
  })

  it.each(['github', 'gitlab', 'onshape', 'someFutureCad'])(
    'routes %s to its own start/exchange endpoints',
    async (provider) => {
      const start = stubClient({ authorize_url: 'u', state: 'st', source_id: 's1' })
      await startOAuth('p1', provider, {}, start.client)
      expect(start.calls[0].path).toBe(`/integrations/${provider}/oauth/start`)

      const exchange = stubClient({ id: 's1', status: 'connected' })
      await exchangeOAuth(provider, { state: 'st', code: 'cd' }, exchange.client)
      expect(exchange.calls[0].path).toBe(`/integrations/${provider}/oauth/exchange`)
    }
  )
})

describe('account connections (SOLUSDEV-241)', () => {
  it("lists and revokes the signed-in user's grants", async () => {
    const list = stubClient([])
    await listConnections(list.client)
    const adopt = stubClient({ adopted: [], skipped: [] })
    await adoptConnections({ source_ids: ['s1'], confirm_access: true }, adopt.client)
    expect(adopt.calls[0].path).toBe('/users/me/connections/adopt')
    expect(adopt.calls[0].options).toMatchObject({
      method: 'POST',
      body: { source_ids: ['s1'], confirm_access: true }
    })
    const legacy = stubClient([])
    await listLegacyConnections(legacy.client)
    expect(legacy.calls[0].path).toBe('/users/me/connections/legacy')
    expect(list.calls[0].path).toBe('/users/me/connections')

    const revoke = stubClient({ id: 'c1', disconnected_sources: 2 })
    await revokeConnection('c1', revoke.client)
    expect(revoke.calls[0]).toEqual({
      path: '/users/me/connections/c1',
      options: { method: 'DELETE' }
    })
  })

  it('reads the cached listing with its meta, and asks again on refresh', async () => {
    const calls: { path: string }[] = []
    const client: ApiClient = {
      request: vi.fn(),
      requestPage: vi.fn(async (path: string) => {
        calls.push({ path })
        return { data: [{ id: 'dA', name: 'Rover' }], meta: { cached: true, fetched_at: 't' } }
      })
    } as unknown as ApiClient
    const listing = await listConnectionDocuments('c1', {}, client)
    expect(listing).toEqual({ items: [{ id: 'dA', name: 'Rover' }], cached: true, fetched_at: 't' })
    expect(calls[0].path).toBe('/users/me/connections/c1/documents')

    await listConnectionDocuments('c1', { refresh: true }, client)
    expect(calls[1].path).toBe('/users/me/connections/c1/documents?refresh=true')
  })

  it('binds a project to a linked account through createSource', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await createSource('p1', { type: 'onshape', name: 'cad', connection_id: 'c1' }, client)
    expect(calls[0]).toEqual({
      path: '/projects/p1/sources',
      options: { method: 'POST', body: { type: 'onshape', name: 'cad', connection_id: 'c1' } }
    })
  })

  it('adds and removes a document on a project source', async () => {
    const add = stubClient({ job_id: 'j1', status: 'queued', source: { id: 's1' } })
    await addSourceDocument('p1', 's1', 'dB', add.client)
    expect(add.calls[0]).toEqual({
      path: '/projects/p1/sources/s1/documents',
      options: { method: 'POST', body: { id: 'dB' } }
    })

    const remove = stubClient({ job_id: 'j2', status: 'queued', source: { id: 's1' } })
    await removeSourceDocument('p1', 's1', 'd/B', remove.client)
    expect(remove.calls[0]).toEqual({
      path: '/projects/p1/sources/s1/documents/d%2FB',
      options: { method: 'DELETE' }
    })
  })
})

describe('personalTeam', () => {
  const me = (teams: Me['teams']): Me => ({
    id: 'u1',
    email: 'a@b.dev',
    name: null,
    avatar_url: null,
    created_at: '',
    teams
  })

  it('prefers the personal team', () => {
    const team = personalTeam(
      me([
        {
          team_id: 't2',
          name: 'Acme',
          role: 'member',
          is_personal: false,
          plan_status: 'trial',
          trial_ends_at: ''
        },
        {
          team_id: 't1',
          name: 'Personal',
          role: 'owner',
          is_personal: true,
          plan_status: 'trial',
          trial_ends_at: ''
        }
      ])
    )
    expect(team?.team_id).toBe('t1')
  })

  it('falls back to the first team when none is personal', () => {
    const team = personalTeam(
      me([
        {
          team_id: 't9',
          name: 'Acme',
          role: 'member',
          is_personal: false,
          plan_status: 'trial',
          trial_ends_at: ''
        }
      ])
    )
    expect(team?.team_id).toBe('t9')
  })
})

describe('team resources', () => {
  teamMembershipAndPaginationTests()
  teamSettingsAndNotificationsTests()
})

describe('project management', () => {
  it('lists projects and can include archived', async () => {
    const { listProjects } = await import('./resources')
    const { client, calls } = stubClient([])
    await listProjects('t1', {}, client)
    expect(calls[0].path).toBe('/teams/t1/projects')
    await listProjects('t1', { includeArchived: true }, client)
    expect(calls[1].path).toBe('/teams/t1/projects?include_archived=true')
  })

  it('renames a project via PATCH', async () => {
    const { updateProject } = await import('./resources')
    const { client, calls } = stubClient({ id: 'p1' })
    await updateProject('p1', { name: 'Rover MK2' }, client)
    expect(calls[0].path).toBe('/projects/p1')
    expect(calls[0].options).toMatchObject({ method: 'PATCH', body: { name: 'Rover MK2' } })
  })

  it('archives and unarchives a project', async () => {
    const { archiveProject, unarchiveProject } = await import('./resources')
    const { client, calls } = stubClient({ id: 'p1' })
    await archiveProject('p1', client)
    expect(calls[0].path).toBe('/projects/p1/archive')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
    await unarchiveProject('p1', client)
    expect(calls[1].path).toBe('/projects/p1/unarchive')
    expect(calls[1].options).toMatchObject({ method: 'POST' })
  })

  it('deletes a project via DELETE', async () => {
    const { deleteProject } = await import('./resources')
    const { client, calls } = stubClient(undefined)
    await deleteProject('p1', client)
    // The API demands ?confirm=true (HOME H5 review).
    expect(calls[0].path).toBe('/projects/p1?confirm=true')
    expect(calls[0].options).toMatchObject({ method: 'DELETE' })
  })
})

describe('settings surfaces (SOLUSDEV-86)', () => {
  it('getSettings reads /users/me/settings', async () => {
    const { getSettings } = await import('./resources')
    const { client, calls } = stubClient({
      sol_mode: 'guide',
      data_collection_consent: true,
      onboarding_step: 'done'
    })
    const s = await getSettings(client)
    expect(calls[0].path).toBe('/users/me/settings')
    expect(s.data_collection_consent).toBe(true)
  })

  it('updateConsent PATCHes the consent flag on /users/me/settings', async () => {
    const { updateConsent } = await import('./resources')
    const { client, calls } = stubClient({
      sol_mode: 'guide',
      data_collection_consent: false,
      onboarding_step: 'done'
    })
    const s = await updateConsent(false, client)
    expect(calls[0].path).toBe('/users/me/settings')
    expect(calls[0].options).toMatchObject({
      method: 'PATCH',
      body: { data_collection_consent: false }
    })
    expect(s.data_collection_consent).toBe(false)
  })

  it('updateProfile PATCHes the display name on /users/me', async () => {
    const { updateProfile } = await import('./resources')
    const { client, calls } = stubClient({ id: 'u1', name: 'Ada Lovelace', teams: [] })
    const me = await updateProfile({ name: 'Ada Lovelace' }, client)
    expect(calls[0].path).toBe('/users/me')
    expect(calls[0].options).toMatchObject({ method: 'PATCH', body: { name: 'Ada Lovelace' } })
    expect(me.name).toBe('Ada Lovelace')
  })

  it('getSubscription reads /users/me/subscription', async () => {
    const { getSubscription } = await import('./resources')
    const { client, calls } = stubClient({
      user_id: 'u1',
      plan: 'pro',
      status: 'trialing',
      limits: { max_integrations: null, max_projects: null, max_teams: null },
      expires_at: '2026-07-22T00:00:00Z',
      seat_count: 3
    })
    const sub = await getSubscription(client)
    expect(calls[0].path).toBe('/users/me/subscription')
    expect(sub.plan).toBe('pro')
    expect(sub.limits.max_projects).toBeNull()
  })
})

describe('workspace service requests', () => {
  it('requests cache-only documents without an implicit refresh', async () => {
    const { client, calls } = stubClient([])
    await listConnectionDocuments('c1', { cacheOnly: true }, client)
    expect(calls[0].path).toBe('/users/me/connections/c1/documents?cache_only=true')
  })
  it('reads the specific accepted job rather than older source sync history', async () => {
    const job = { id: 'j1', project_id: 'p1', status: 'succeeded', error: null }
    const { client, calls } = stubClient(job)
    expect(await getJob('j1', client)).toEqual(job)
    expect(calls[0].path).toBe('/jobs/j1')
  })
})

it('listAllSources follows every source page so existing document bindings are retained', async () => {
  const { listAllSources } = await import('./resources')
  const { client } = stubClient([])
  vi.mocked(client.requestPage)
    .mockResolvedValueOnce({ data: [{ id: 'first' }], meta: { has_next: true, next_cursor: 'c2' } })
    .mockResolvedValueOnce({ data: [{ id: 'last' }], meta: { has_next: false } })
  expect(await listAllSources('p1', client)).toEqual([{ id: 'first' }, { id: 'last' }])
  expect(client.requestPage).toHaveBeenNthCalledWith(2, '/projects/p1/sources?limit=200&cursor=c2')
})

function sourceApiRoutesTests(): void {
  it('listIntegrations hits /integrations', async () => {
    const { client, calls } = stubClient([])
    await listIntegrations(client)
    expect(calls[0].path).toBe('/integrations')
  })

  it('listSources scopes to the project', async () => {
    const { client, calls } = stubClient([])
    await listSources('p1', client)
    expect(calls[0].path).toBe('/projects/p1/sources')
  })

  it('getSource hits the single-source route', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await getSource('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1')
  })

  it('listSelectable hits the generic picker route under the source', async () => {
    const { client, calls } = stubClient([])
    await listSelectable('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1/selectable')
  })

  it('updateSource PATCHes the source config', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await updateSource('p1', 's1', { config: { repo: 'o/r', branch: 'main' } }, client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1')
    expect(calls[0].options).toMatchObject({
      method: 'PATCH',
      body: { config: { repo: 'o/r', branch: 'main' } }
    })
  })

  it('disconnectSource DELETEs the source, retaining entities by default', async () => {
    const { client, calls } = stubClient({ id: 's1', retained_entities: true })
    await disconnectSource('p1', 's1', {}, client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1?retain_entities=true')
    expect((calls[0].options as { method?: string }).method).toBe('DELETE')
  })

  it('disconnectSource can remove entities when asked', async () => {
    const { client, calls } = stubClient({ id: 's1', retained_entities: false })
    await disconnectSource('p1', 's1', { retainEntities: false }, client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1?retain_entities=false')
  })

  it('triggerSync POSTs to the sync route', async () => {
    const { client, calls } = stubClient({ job_id: 'j1', status: 'queued' })
    await triggerSync('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1/sync')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
  })

  it('getSyncs reads the sync history', async () => {
    const { client, calls } = stubClient([])
    await getSyncs('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1/syncs')
  })
}

function graphApiQueriesTests(): void {
  it('getGraphNeighborhood requests the focused entity with a bounded depth', async () => {
    const { client, calls } = stubClient({ entities: [], edges: [], truncated: false })
    await getGraphNeighborhood('p1', 'e1', {}, client)
    expect(calls[0].path).toBe('/projects/p1/graph?root=e1&depth=1')
  })

  it('getGraphNeighborhood passes filters and limit through', async () => {
    const { client, calls } = stubClient({ entities: [], edges: [], truncated: false })
    await getGraphNeighborhood(
      'p1',
      'e1',
      { depth: 2, entity_types: ['ic', 'motor'], relation_types: ['drives'], limit: 50 },
      client
    )
    expect(calls[0].path).toBe(
      '/projects/p1/graph?root=e1&depth=2&entity_types=ic%2Cmotor&relation_types=drives&limit=50'
    )
  })

  it('listEntities builds a filtered query string', async () => {
    const { client, calls } = stubClient([])
    await listEntities('p1', { type: 'code_module', source_id: 's1' }, client)
    expect(calls[0].path).toBe('/projects/p1/entities?type=code_module&source_id=s1')
  })

  it('listEntities omits the query when no filters are given', async () => {
    const { client, calls } = stubClient([])
    await listEntities('p1', {}, client)
    expect(calls[0].path).toBe('/projects/p1/entities')
  })

  it('listAllEntities follows the cursor until the last page', async () => {
    const pages = [
      { data: [{ id: 'e1' }, { id: 'e2' }], meta: { has_next: true, next_cursor: 'cur2' } },
      { data: [{ id: 'e3' }], meta: { has_next: false, next_cursor: null } }
    ]
    const calls: string[] = []
    const client: ApiClient = {
      request: vi.fn(),
      requestPage: vi.fn(async (path: string) => {
        calls.push(path)
        return pages[calls.length - 1] as never
      })
    }
    const { listAllEntities } = await import('./resources')
    const all = await listAllEntities('p1', client)
    expect(all.map((e) => e.id)).toEqual(['e1', 'e2', 'e3'])
    expect(calls).toEqual([
      '/projects/p1/entities?limit=500',
      '/projects/p1/entities?limit=500&cursor=cur2'
    ])
  })
}

function teamMembershipAndPaginationTests(): void {
  it('lists members and changes a role', async () => {
    const { listMembers, changeMemberRole } = await import('./resources')
    const { client, calls } = stubClient([])
    await listMembers('t1', client)
    expect(calls[0].path).toBe('/teams/t1/members')
    await changeMemberRole('t1', 'u2', 'admin', client)
    expect(calls[1].path).toBe('/teams/t1/members/u2')
    expect(calls[1].options).toMatchObject({ method: 'PATCH', body: { role: 'admin' } })
  })

  it('creates and revokes invites', async () => {
    const { createInvite, revokeInvite } = await import('./resources')
    const { client, calls } = stubClient({})
    await createInvite('t1', { email: 'x@y.dev', role: 'member' }, client)
    expect(calls[0].path).toBe('/teams/t1/invites')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
    await revokeInvite('t1', 'i9', client)
    expect(calls[1].path).toBe('/teams/t1/invites/i9')
    expect(calls[1].options).toMatchObject({ method: 'DELETE' })
  })

  it('deletes a team', async () => {
    const { deleteTeam } = await import('./resources')
    const { client, calls } = stubClient(undefined)
    await deleteTeam('t1', client)
    // The API demands ?confirm=true (found in the HOME H5 live run).
    expect(calls[0].path).toBe('/teams/t1?confirm=true')
    expect(calls[0].options).toMatchObject({ method: 'DELETE' })
  })

  it('paginated list variants pass the cursor through as a query param', async () => {
    const { listActivityPage, listNotificationsPage } = await import('./resources')
    const { client, calls } = stubClient([])
    await listActivityPage('t1', { cursor: 'cur9' }, client)
    await listActivityPage('t1', {}, client)
    await listActivityPage('t1', { projectId: 'p1', limit: 3 }, client)
    await listNotificationsPage('cur9', client)
    await listNotificationsPage(undefined, client)
    expect(calls.map((c) => c.path)).toEqual([
      '/teams/t1/activity?cursor=cur9',
      '/teams/t1/activity',
      '/teams/t1/activity?limit=3&project_id=p1',
      '/users/me/notifications?cursor=cur9',
      '/users/me/notifications'
    ])
  })

  it('activity page requests carry limit and cursor together', async () => {
    const { listActivityPage } = await import('./resources')
    const { client, calls } = stubClient([])
    await listActivityPage('t1', { limit: 100 }, client)
    await listActivityPage('t1', { cursor: 'cur9', limit: 25 }, client)
    expect(calls.map((c) => c.path)).toEqual([
      '/teams/t1/activity?limit=100',
      '/teams/t1/activity?cursor=cur9&limit=25'
    ])
  })
}

function teamSettingsAndNotificationsTests(): void {
  it('updates and clears the SOL custom instruction (SOLUSDEV-233)', async () => {
    const { updateCustomInstruction } = await import('./resources')
    const { client, calls } = stubClient({})
    await updateCustomInstruction('Prefer metric units.', client)
    await updateCustomInstruction(null, client)
    expect(calls[0].path).toBe('/users/me/settings')
    expect(calls[0].options).toMatchObject({
      method: 'PATCH',
      body: { sol_custom_instruction: 'Prefer metric units.' }
    })
    expect(calls[1].options).toMatchObject({ body: { sol_custom_instruction: null } })
  })

  it('fetches the credit usage meter (SOLUSDEV-233)', async () => {
    const { getUsage } = await import('./resources')
    const { client, calls } = stubClient({ used: 941, allowance: 10000, balance: 9059 })
    const usage = await getUsage(client)
    expect(calls[0].path).toBe('/users/me/usage')
    expect(usage.used).toBe(941)
  })

  it('fetches team detail, activity, and notifications', async () => {
    const { getTeamDetail, listNotifications, markNotificationRead, updateTeam } =
      await import('./resources')
    const { client, calls } = stubClient([])
    await getTeamDetail('t1', client)
    await listNotifications(client)
    await markNotificationRead('n1', client)
    await updateTeam('t1', { settings: { notify_project_created: false } }, client)
    expect(calls.map((c) => c.path)).toEqual([
      '/teams/t1',
      '/users/me/notifications',
      '/users/me/notifications/n1/read',
      '/teams/t1'
    ])
  })

  it('accepts an invite by token', async () => {
    const { acceptInvite } = await import('./resources')
    const { client, calls } = stubClient({ team_id: 't1', role: 'member' })
    const result = await acceptInvite('tok_abc', client)
    expect(calls[0].path).toBe('/invites/tok_abc/accept')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
    expect(result).toMatchObject({ team_id: 't1', role: 'member' })
  })

  it('percent-encodes an invite token so it cannot alter the path', async () => {
    const { acceptInvite } = await import('./resources')
    const { client, calls } = stubClient({ team_id: 't1', role: 'member' })
    await acceptInvite('a/b?c', client)
    expect(calls[0].path).toBe('/invites/a%2Fb%3Fc/accept')
  })

  it('marks all notifications read', async () => {
    const { markAllNotificationsRead } = await import('./resources')
    const { client, calls } = stubClient({ updated: 3 })
    const result = await markAllNotificationsRead(client)
    expect(calls[0].path).toBe('/users/me/notifications/read-all')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
    expect(result).toMatchObject({ updated: 3 })
  })
}
