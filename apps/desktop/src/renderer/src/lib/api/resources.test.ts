import { describe, it, expect, vi } from 'vitest'
import {
  getMe,
  updateSolMode,
  createProject,
  getProject,
  solModeToApi,
  personalTeam,
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
