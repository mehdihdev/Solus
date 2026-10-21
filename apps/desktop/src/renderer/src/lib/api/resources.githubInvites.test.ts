// SOLUSDEV-216: the extended invite + source-create calls.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from './client'
import { createInvite, createSource } from './resources'

function stub(): {
  client: ApiClient
  calls: { path: string; options?: { method?: string; body?: unknown } }[]
} {
  const calls: { path: string; options?: { method?: string; body?: unknown } }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: { method?: string; body?: unknown }) => {
      calls.push({ path, options })
      return {} as never
    }),
    requestPage: vi.fn()
  }
  return { client, calls }
}

describe('createInvite', () => {
  it('still sends an email invite unchanged', async () => {
    const { client, calls } = stub()
    await createInvite('t1', { email: 'a@b.co', role: 'member' }, client)
    expect(calls[0]).toEqual({
      path: '/teams/t1/invites',
      options: { method: 'POST', body: { email: 'a@b.co', role: 'member' } }
    })
  })

  it('sends a github target with the numeric id and display login', async () => {
    const { client, calls } = stub()
    await createInvite(
      't1',
      { github_user_id: 583231, github_login: 'octocat', role: 'viewer' },
      client
    )
    expect(calls[0]).toEqual({
      path: '/teams/t1/invites',
      options: {
        method: 'POST',
        body: { github_user_id: 583231, github_login: 'octocat', role: 'viewer' }
      }
    })
    expect(calls[0].options?.body).not.toHaveProperty('email')
  })
})

describe('createSource', () => {
  it('sends installation: true for a team-installation bind', async () => {
    const { client, calls } = stub()
    await createSource(
      'p1',
      {
        type: 'github',
        name: 'robot',
        config: { repo: 'acme/robot', branch: 'main' },
        installation: true
      },
      client
    )
    expect(calls[0]).toEqual({
      path: '/projects/p1/sources',
      options: {
        method: 'POST',
        body: {
          type: 'github',
          name: 'robot',
          config: { repo: 'acme/robot', branch: 'main' },
          installation: true
        }
      }
    })
    expect(calls[0].options?.body).not.toHaveProperty('connection_id')
  })

  it('still passes connection_id through', async () => {
    const { client, calls } = stub()
    await createSource('p1', { type: 'github', name: 'r', connection_id: 'c1' }, client)
    expect(calls[0].options?.body).toEqual({ type: 'github', name: 'r', connection_id: 'c1' })
  })
})
