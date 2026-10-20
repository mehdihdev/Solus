// SOLUSDEV-317: the GitHub org member assignment contract (ADR-039 amendment
// 2026-10-19, spec §3.2) against a fake ApiClient.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import {
  assignGithubMember,
  githubErrorLogin,
  githubOrgErrorCode,
  unassignGithubMember,
  type GithubAssignment
} from './resources.teamGithub'

interface Call {
  path: string
  options?: { method?: string; body?: unknown }
}

const ASSIGNMENT: GithubAssignment = {
  user_id: 'u2',
  name: 'Noor',
  email: 'noor@team.dev',
  source: 'admin',
  assigned_by: { user_id: 'u1', name: 'Ada' },
  assigned_at: '2026-10-19T00:00:00Z'
}

function stub(data: unknown): { client: ApiClient; calls: Call[] } {
  const calls: Call[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return data as never
    }),
    requestPage: vi.fn()
  }
  return { client, calls }
}

describe('assignGithubMember', () => {
  it('PUTs the user_id and unwraps the assignment', async () => {
    const { client, calls } = stub({ assignment: ASSIGNMENT })
    expect(await assignGithubMember('t1', 42, 'u2', client)).toEqual(ASSIGNMENT)
    expect(calls[0]).toEqual({
      path: '/teams/t1/github/members/42/assignment',
      options: { method: 'PUT', body: { user_id: 'u2' } }
    })
  })

  it('encodes the team id', async () => {
    const { client, calls } = stub({ assignment: ASSIGNMENT })
    await assignGithubMember('a/b', 1, 'u2', client)
    expect(calls[0].path).toBe('/teams/a%2Fb/github/members/1/assignment')
  })
})

describe('unassignGithubMember', () => {
  it('DELETEs the assignment (204, no body)', async () => {
    const { client, calls } = stub(undefined)
    await expect(unassignGithubMember('t1', 42, client)).resolves.toBeUndefined()
    expect(calls[0]).toEqual({
      path: '/teams/t1/github/members/42/assignment',
      options: { method: 'DELETE' }
    })
  })
})

describe('assignment error codes', () => {
  it.each([
    'not_a_team_member',
    'github_identity_verified',
    'member_has_verified_github',
    'member_already_assigned',
    'assignment_missing'
  ])('narrows %s', (code) => {
    expect(githubOrgErrorCode(new ApiError(409, code, 'm'))).toBe(code)
  })

  it('propagates a refusal through the wrapper', async () => {
    const client: ApiClient = {
      request: vi.fn(async () => {
        throw new ApiError(409, 'member_already_assigned', 'x')
      }),
      requestPage: vi.fn()
    }
    const err = await assignGithubMember('t1', 1, 'u2', client).catch((e: unknown) => e)
    expect(githubOrgErrorCode(err)).toBe('member_already_assigned')
  })
})

describe('githubErrorLogin', () => {
  it('reads the github_login the refusal details name', () => {
    const err = new ApiError(409, 'member_already_assigned', 'x', [
      { github_id: 9, github_login: 'noor-a' }
    ])
    expect(githubErrorLogin(err)).toBe('noor-a')
  })

  it('is null without details, with a non-string login, or for a non-ApiError', () => {
    expect(githubErrorLogin(new ApiError(409, 'member_already_assigned', 'x'))).toBeNull()
    expect(
      githubErrorLogin(new ApiError(409, 'x', 'x', [{ github_login: 5 }, null, 'str']))
    ).toBeNull()
    expect(githubErrorLogin(new Error('x'))).toBeNull()
  })
})
