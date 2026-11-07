// SOLUSDEV-319: "Invitations to me" wire contract (API-implementation.md §4), against a fake ApiClient.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import {
  acceptMyInvite,
  declineMyInvite,
  listMyInvites,
  myInviteRefusal,
  type MyInvite
} from './resources.myInvites'

interface Call {
  path: string
  options?: { method?: string; body?: unknown }
}

const INVITE: MyInvite = {
  id: 'inv-1',
  team: { id: 't-9', name: 'Bracket Labs' },
  role: 'member',
  invited_by: { name: 'Lena V' },
  created_at: '2026-11-05T10:00:00Z',
  expires_at: '2026-11-12T10:00:00Z'
}

function stub(data: unknown): { client: ApiClient; calls: Call[] } {
  const calls: Call[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return data as never
    }),
    requestPage: vi.fn(async () => ({ data, meta: {} }) as never)
  }
  return { client, calls }
}

describe('my invites client', () => {
  it('lists the invites waiting for me', async () => {
    const { client, calls } = stub([INVITE])
    expect(await listMyInvites(client)).toEqual([INVITE])
    expect(calls).toEqual([{ path: '/users/me/invites', options: undefined }])
  })

  it('accepts one by id and returns the joined team', async () => {
    const { client, calls } = stub({ team_id: 't-9', role: 'member' })
    expect(await acceptMyInvite('inv-1', client)).toEqual({ team_id: 't-9', role: 'member' })
    expect(calls[0]).toEqual({
      path: '/users/me/invites/inv-1/accept',
      options: { method: 'POST' }
    })
  })

  it('declines one by id', async () => {
    const { client, calls } = stub(null)
    await declineMyInvite('inv-1', client)
    expect(calls[0]).toEqual({
      path: '/users/me/invites/inv-1/decline',
      options: { method: 'POST' }
    })
  })

  it('encodes the id so it can never change the path', async () => {
    const { client, calls } = stub(null)
    await declineMyInvite('../x?y', client)
    expect(calls[0].path).toBe('/users/me/invites/..%2Fx%3Fy/decline')
  })
})

describe('myInviteRefusal', () => {
  const error = (status: number, code: string): ApiError => new ApiError(status, code, code)

  it('names the refusals the rail words differently', () => {
    expect(myInviteRefusal(error(403, 'email_not_verified'))).toBe('unverified')
    expect(myInviteRefusal(error(409, 'plan_limit_reached'))).toBe('at_limit')
    expect(myInviteRefusal(error(410, 'invite_expired'))).toBe('gone')
    expect(myInviteRefusal(error(409, 'invite_revoked'))).toBe('gone')
    expect(myInviteRefusal(error(409, 'invite_declined'))).toBe('gone')
    expect(myInviteRefusal(error(404, 'not_found'))).toBe('gone')
    expect(myInviteRefusal(error(409, 'already_member'))).toBe('already_member')
  })

  it('treats anything else as a plain failure', () => {
    expect(myInviteRefusal(error(500, 'internal'))).toBe('failed')
    expect(myInviteRefusal(new Error('offline'))).toBe('failed')
  })
})
