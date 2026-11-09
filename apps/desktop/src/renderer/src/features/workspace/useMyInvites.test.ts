// SOLUSDEV-319 (multi-team Home): the invitations waiting for me in the team rail —
// loaded once per mount, accepted or declined in place, each refusal named.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../lib/api/resources.myInvites'
import { ApiError } from '../../lib/api/envelope.types'
import { useMyInvites } from './useMyInvites'

vi.mock('../../lib/api/resources.myInvites', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.myInvites')>()),
  listMyInvites: vi.fn(),
  acceptMyInvite: vi.fn(),
  declineMyInvite: vi.fn()
}))

const BRACKET: client.MyInvite = {
  id: 'inv-1',
  team: { id: 't-9', name: 'Bracket Labs' },
  role: 'member',
  invited_by: { name: 'Lena V' },
  created_at: '2026-11-05T10:00:00Z',
  expires_at: '2026-11-12T10:00:00Z'
}
const ROVER: client.MyInvite = { ...BRACKET, id: 'inv-2', team: { id: 't-8', name: 'Rover' } }

beforeEach(() => {
  vi.mocked(client.listMyInvites).mockReset().mockResolvedValue([BRACKET, ROVER])
  vi.mocked(client.acceptMyInvite).mockReset()
  vi.mocked(client.declineMyInvite).mockReset()
})

describe('useMyInvites', () => {
  it('loads the invites waiting for me', async () => {
    const { result } = renderHook(() => useMyInvites(vi.fn()))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.invites.map((i) => i.id)).toEqual(['inv-1', 'inv-2'])
  })

  it('says so when my email is not verified yet', async () => {
    vi.mocked(client.listMyInvites).mockRejectedValue(
      new ApiError(403, 'email_not_verified', 'verify')
    )
    const { result } = renderHook(() => useMyInvites(vi.fn()))
    await waitFor(() => expect(result.current.status).toBe('unverified'))
    expect(result.current.invites).toEqual([])
  })

  it('accepting joins, drops the row and hands the new team to the caller', async () => {
    vi.mocked(client.acceptMyInvite).mockResolvedValue({ team_id: 't-9', role: 'member' })
    const onJoined = vi.fn()
    const { result } = renderHook(() => useMyInvites(onJoined))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(() => result.current.accept('inv-1'))

    expect(client.acceptMyInvite).toHaveBeenCalledWith('inv-1')
    expect(onJoined).toHaveBeenCalledWith('t-9')
    expect(result.current.invites.map((i) => i.id)).toEqual(['inv-2'])
    expect(result.current.notice).toBeNull()
  })

  it('declining drops the row without joining', async () => {
    vi.mocked(client.declineMyInvite).mockResolvedValue(undefined)
    const onJoined = vi.fn()
    const { result } = renderHook(() => useMyInvites(onJoined))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(() => result.current.decline('inv-2'))

    expect(client.declineMyInvite).toHaveBeenCalledWith('inv-2')
    expect(onJoined).not.toHaveBeenCalled()
    expect(result.current.invites.map((i) => i.id)).toEqual(['inv-1'])
  })

  it('an invite that closed meanwhile leaves the list with a note', async () => {
    vi.mocked(client.acceptMyInvite).mockRejectedValue(
      new ApiError(409, 'invite_revoked', 'revoked')
    )
    const { result } = renderHook(() => useMyInvites(vi.fn()))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(() => result.current.accept('inv-1'))

    expect(result.current.invites.map((i) => i.id)).toEqual(['inv-2'])
    expect(result.current.notice).toEqual({ inviteId: 'inv-1', refusal: 'gone' })
  })

  it('a plan limit keeps the invite and names the refusal', async () => {
    vi.mocked(client.acceptMyInvite).mockRejectedValue(
      new ApiError(409, 'plan_limit_reached', 'limit')
    )
    const { result } = renderHook(() => useMyInvites(vi.fn()))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(() => result.current.accept('inv-1'))

    expect(result.current.invites.map((i) => i.id)).toEqual(['inv-1', 'inv-2'])
    expect(result.current.notice).toEqual({ inviteId: 'inv-1', refusal: 'at_limit' })
  })

  it('marks the row busy while its request is in flight', async () => {
    let finish: () => void = () => undefined
    vi.mocked(client.declineMyInvite).mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve
      })
    )
    const { result } = renderHook(() => useMyInvites(vi.fn()))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    let pending: Promise<void> = Promise.resolve()
    act(() => {
      pending = result.current.decline('inv-1')
    })
    expect(result.current.busyId).toBe('inv-1')
    await act(async () => {
      finish()
      await pending
    })
    expect(result.current.busyId).toBeNull()
  })
})
