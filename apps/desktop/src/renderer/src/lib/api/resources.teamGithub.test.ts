// SOLUSDEV-216: docs/api/github-orgs.md wire contract, against a fake ApiClient.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import {
  GITHUB_ORG_ERROR_CODES,
  completeGithubInstall,
  getTeamInstallation,
  githubOrgErrorCode,
  listTeamGithubMembers,
  listTeamGithubRepos,
  startGithubInstall,
  unlinkTeamInstallation,
  type TeamInstallation
} from './resources.teamGithub'

interface Call {
  path: string
  options?: { method?: string; body?: unknown }
}

const INSTALLATION: TeamInstallation = {
  id: 'ti-1',
  provider: 'github',
  account_login: 'acme',
  account_type: 'Organization',
  account_avatar_url: null,
  repository_selection: 'selected',
  status: 'active',
  linked_by: { user_id: 'u1', name: 'Ada' },
  linked_at: '2026-10-17T00:00:00Z',
  html_url: 'https://github.com/acme',
  manage_url: 'https://github.com/organizations/acme/settings/installations/1'
}

function stub(
  data: unknown = {},
  meta: Record<string, unknown> = {}
): { client: ApiClient; calls: Call[] } {
  const calls: Call[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return data as never
    }),
    requestPage: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return { data, meta } as never
    })
  }
  return { client, calls }
}

describe('startGithubInstall', () => {
  it('POSTs the redirect_uri and returns the install triple', async () => {
    const body = {
      install_url: 'https://github.com/apps/solus/installations/new?state=s',
      state: 's',
      redirect_uri: 'http://localhost:53682/auth/callback'
    }
    const { client, calls } = stub(body)
    const out = await startGithubInstall('t1', 'http://localhost:53682/auth/callback', client)
    expect(out).toEqual(body)
    expect(calls[0]).toEqual({
      path: '/teams/t1/github/install/start',
      options: { method: 'POST', body: { redirect_uri: 'http://localhost:53682/auth/callback' } }
    })
  })

  it('sends an empty body when no redirect_uri is given', async () => {
    const { client, calls } = stub({})
    await startGithubInstall('t1', undefined, client)
    expect(calls[0].options?.body).toEqual({})
  })

  it('encodes the team id in the path', async () => {
    const { client, calls } = stub({})
    await startGithubInstall('a/b', undefined, client)
    expect(calls[0].path).toBe('/teams/a%2Fb/github/install/start')
  })
})

describe('completeGithubInstall', () => {
  it('maps a 201 body to linked', async () => {
    const { client, calls } = stub({ installation: INSTALLATION })
    const out = await completeGithubInstall(
      't1',
      { state: 's', code: 'c', installation_id: 9, setup_action: 'install' },
      client
    )
    expect(out).toEqual({ kind: 'linked', installation: INSTALLATION })
    expect(calls[0]).toEqual({
      path: '/teams/t1/github/install/complete',
      options: {
        method: 'POST',
        body: { state: 's', code: 'c', installation_id: 9, setup_action: 'install' }
      }
    })
  })

  it('maps the 202 requested body to requested and sends no installation_id', async () => {
    const { client, calls } = stub({ status: 'requested' })
    const out = await completeGithubInstall(
      't1',
      { state: 's', code: 'c', setup_action: 'request' },
      client
    )
    expect(out).toEqual({ kind: 'requested' })
    expect(calls[0].options?.body).toEqual({ state: 's', code: 'c', setup_action: 'request' })
  })
})

describe('getTeamInstallation', () => {
  it('unwraps the installation', async () => {
    const { client, calls } = stub({ installation: INSTALLATION })
    expect(await getTeamInstallation('t1', client)).toEqual(INSTALLATION)
    expect(calls[0]).toEqual({ path: '/teams/t1/github/installation', options: undefined })
  })

  it('returns null when nothing is linked (or a personal team)', async () => {
    const { client } = stub({ installation: null })
    expect(await getTeamInstallation('t1', client)).toBeNull()
  })
})

describe('unlinkTeamInstallation', () => {
  it('DELETEs and returns disabled_sources and manage_url', async () => {
    const body = { disabled_sources: 3, manage_url: INSTALLATION.manage_url }
    const { client, calls } = stub(body)
    expect(await unlinkTeamInstallation('t1', client)).toEqual(body)
    expect(calls[0]).toEqual({
      path: '/teams/t1/github/installation',
      options: { method: 'DELETE' }
    })
  })
})

describe('listTeamGithubRepos', () => {
  const items = [
    {
      id: 'acme/robot',
      name: 'acme/robot',
      subtitle: 'private',
      config: { repo: 'acme/robot', branch: 'main' }
    }
  ]

  it('returns items with total and next cursor from the envelope meta', async () => {
    const { client, calls } = stub(items, { total: 12, next_cursor: 'c2', has_next: true })
    const out = await listTeamGithubRepos('t1', {}, client)
    expect(out).toEqual({ items, total: 12, cursor: 'c2' })
    expect(calls[0].path).toBe('/teams/t1/github/repos')
  })

  it('builds the query from cursor, limit and q', async () => {
    const { client, calls } = stub(items, {})
    const out = await listTeamGithubRepos('t1', { cursor: 'c1', limit: 25, q: 'rob ot' }, client)
    expect(out.total).toBeNull()
    expect(out.cursor).toBeNull()
    const url = new URL(`http://x${calls[0].path}`)
    expect(url.pathname).toBe('/teams/t1/github/repos')
    expect(url.searchParams.get('cursor')).toBe('c1')
    expect(url.searchParams.get('limit')).toBe('25')
    expect(url.searchParams.get('q')).toBe('rob ot')
  })

  it('omits empty q and cursor', async () => {
    const { client, calls } = stub([], {})
    await listTeamGithubRepos('t1', { q: '', cursor: '' }, client)
    expect(calls[0].path).toBe('/teams/t1/github/repos')
  })
})

describe('listTeamGithubMembers', () => {
  it('GETs members with paging and returns the roster', async () => {
    const roster = [
      { github_id: 5, github_login: 'ada', avatar_url: 'https://a/5', solus_status: 'not_on_solus' }
    ]
    const { client, calls } = stub(roster, { total: 1, next_cursor: null })
    const out = await listTeamGithubMembers('t1', { cursor: 'x', limit: 50 }, client)
    expect(out).toEqual({ items: roster, total: 1, cursor: null })
    expect(calls[0].path).toBe('/teams/t1/github/members?cursor=x&limit=50')
  })
})

describe('githubOrgErrorCode', () => {
  it.each(GITHUB_ORG_ERROR_CODES)('maps %s', (code) => {
    expect(githubOrgErrorCode(new ApiError(409, code, 'm'))).toBe(code)
  })

  it('lists exactly the documented codes', () => {
    expect([...GITHUB_ORG_ERROR_CODES].sort()).toEqual(
      [
        'personal_team_unsupported',
        'already_linked',
        'installation_linked_elsewhere',
        'installation_not_accessible',
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
      ].sort()
    )
  })

  it('returns null for an unknown code, a non-ApiError and look-alikes', () => {
    expect(githubOrgErrorCode(new ApiError(500, 'internal_error', 'm'))).toBeNull()
    expect(githubOrgErrorCode(new Error('already_linked'))).toBeNull()
    expect(githubOrgErrorCode({ code: 'already_linked' })).toBeNull()
    expect(githubOrgErrorCode(null)).toBeNull()
    expect(githubOrgErrorCode(undefined)).toBeNull()
  })

  it('propagates server errors through the wrappers so callers can narrow them', async () => {
    const client: ApiClient = {
      request: vi.fn(async () => {
        throw new ApiError(409, 'already_linked', 'Team already linked')
      }),
      requestPage: vi.fn()
    }
    const err = await startGithubInstall('t1', undefined, client).catch((e: unknown) => e)
    expect(githubOrgErrorCode(err)).toBe('already_linked')
  })
})
