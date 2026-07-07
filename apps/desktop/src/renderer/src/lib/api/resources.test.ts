import { describe, it, expect, vi } from 'vitest'
import {
  getMe,
  updateSolMode,
  createProject,
  getProject,
  solModeToApi,
  personalTeam,
  listIntegrations,
  listSources,
  getSource,
  listRepos,
  startGithubOAuth,
  exchangeGithubOAuth,
  updateSource,
  triggerSync,
  getSyncs,
  listEntities,
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

describe('resource calls', () => {
  it('getMe hits /users/me', async () => {
    const { client, calls } = stubClient({ id: 'u1', teams: [] })
    await getMe(client)
    expect(calls[0].path).toBe('/users/me')
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

  it('listRepos hits the repos route under the source', async () => {
    const { client, calls } = stubClient([])
    await listRepos('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/sources/s1/repos')
  })

  it('startGithubOAuth POSTs project_id plus the redirect uri', async () => {
    const { client, calls } = stubClient({ authorize_url: 'u', state: 'st', source_id: 's1' })
    await startGithubOAuth('p1', { redirect_uri: 'http://127.0.0.1:9/cb' }, client)
    expect(calls[0].path).toBe('/integrations/github/oauth/start')
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { project_id: 'p1', redirect_uri: 'http://127.0.0.1:9/cb' }
    })
  })

  it('exchangeGithubOAuth POSTs the state + code', async () => {
    const { client, calls } = stubClient({ id: 's1', status: 'connected' })
    await exchangeGithubOAuth({ state: 'st', code: 'cd' }, client)
    expect(calls[0].path).toBe('/integrations/github/oauth/exchange')
    expect(calls[0].options).toMatchObject({ method: 'POST', body: { state: 'st', code: 'cd' } })
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
    expect(calls[0].path).toBe('/teams/t1')
    expect(calls[0].options).toMatchObject({ method: 'DELETE' })
  })

  it('fetches team detail, activity, and notifications', async () => {
    const { getTeamDetail, listActivity, listNotifications, markNotificationRead, updateTeam } =
      await import('./resources')
    const { client, calls } = stubClient([])
    await getTeamDetail('t1', client)
    await listActivity('t1', client)
    await listNotifications(client)
    await markNotificationRead('n1', client)
    await updateTeam('t1', { settings: { notify_project_created: false } }, client)
    expect(calls.map((c) => c.path)).toEqual([
      '/teams/t1',
      '/teams/t1/activity',
      '/users/me/notifications',
      '/users/me/notifications/n1/read',
      '/teams/t1'
    ])
  })
})
