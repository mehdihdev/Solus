import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import * as resources from '../../lib/api/resources'
import * as online from './workspaceOnline'
import { MOVE_BATCH, linkedAccountFor, useAccountConnections } from './useAccountConnections'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    adoptConnections: vi.fn(),
    listConnections: vi.fn(),
    listLegacyConnections: vi.fn(),
    revokeConnection: vi.fn()
  }
})

const mockedList = vi.mocked(resources.listConnections)
const mockedAdopt = vi.mocked(resources.adoptConnections)
const mockedLegacy = vi.mocked(resources.listLegacyConnections)
const mockedRevoke = vi.mocked(resources.revokeConnection)

const ONSHAPE: resources.Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'ada@example.com',
  access: 'read',
  needs_reauth: null,
  last_error: null,
  projects: [{ project_id: 'p1', name: 'Rover' }],
  created_at: '',
  updated_at: ''
}

beforeEach(() => {
  vi.spyOn(online, 'useWorkspaceFetchEnabled').mockReturnValue(true)
  mockedList.mockReset()
  mockedRevoke.mockReset()
  mockedAdopt.mockReset()
  mockedLegacy.mockReset()
  mockedLegacy.mockResolvedValue([])
})

describe('useAccountConnections — adoption first (SOLUSDEV-242 / H2)', () => {
  it('never moves anything as a side effect of loading — the move is an explicit action', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    const legacy = {
      provider: 'onshape',
      account_login: 'ada',
      projects: [{ project_id: 'p1', name: 'Rover' }],
      source_ids: ['s1'],
      claimable_connection_id: 'c1'
    }
    mockedLegacy.mockResolvedValue([legacy])
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(mockedAdopt).not.toHaveBeenCalled()
    mockedAdopt.mockResolvedValue({
      adopted: [{ connection_id: 'c1', provider: 'onshape', source_id: 's1', project_id: 'p1' }],
      skipped: []
    })
    let moved = false
    await act(async () => {
      moved = await result.current.move(legacy, ONSHAPE)
    })
    expect(moved).toBe(true)
    // A read grant is no acceptance of widening: confirm_access stays false.
    expect(mockedAdopt).toHaveBeenCalledWith({ source_ids: ['s1'], confirm_access: false })
    expect(mockedList).toHaveBeenCalledTimes(2) // re-read after the move
    await act(async () => {
      await result.current.move(legacy, { ...ONSHAPE, access: 'write' })
    })
    expect(mockedAdopt).toHaveBeenLastCalledWith({ source_ids: ['s1'], confirm_access: true })
  })

  it('reports a move that moved nothing or failed as false', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    const legacy = {
      provider: 'onshape',
      account_login: null,
      projects: [],
      source_ids: ['s1'],
      claimable_connection_id: 'c1'
    }
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mockedAdopt.mockResolvedValue({
      adopted: [],
      skipped: [{ source_id: 's1', project_id: 'p1', reason: 'access_mismatch' }]
    })
    await act(async () => {
      expect(await result.current.move(legacy, ONSHAPE)).toBe(false)
    })
    mockedAdopt.mockRejectedValue(new Error('500'))
    await act(async () => {
      expect(await result.current.move(legacy, ONSHAPE)).toBe(false)
    })
  })

  it('lists the unclaimed legacy grants alongside the accounts, and a failed legacy read is empty', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    mockedLegacy.mockResolvedValue([
      {
        provider: 'github',
        account_login: 'octo',
        projects: [],
        source_ids: ['s1'],
        claimable_connection_id: null
      }
    ])
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.legacy.map((l) => l.provider)).toEqual(['github'])
    mockedLegacy.mockRejectedValue(new Error('500'))
    await act(() => result.current.refresh())
    expect(result.current.legacy).toEqual([])
    expect(result.current.connections).toEqual([ONSHAPE])
  })
})

describe('useAccountConnections — batches (SOLUSDEV-242 / H2)', () => {
  it('moves more ids than the server cap in batches', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    const ids = Array.from({ length: MOVE_BATCH + 3 }, (_, i) => `s${i}`)
    const legacy = {
      provider: 'onshape',
      account_login: null,
      projects: [],
      source_ids: ids,
      claimable_connection_id: 'c1'
    }
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mockedAdopt.mockImplementation(async ({ source_ids }) => ({
      adopted: source_ids.map((id) => ({
        connection_id: 'c1',
        provider: 'onshape',
        source_id: id,
        project_id: 'p'
      })),
      skipped: []
    }))
    await act(async () => {
      expect(await result.current.move(legacy, ONSHAPE)).toBe(true)
    })
    expect(mockedAdopt).toHaveBeenCalledTimes(2)
    expect(mockedAdopt.mock.calls[0][0].source_ids).toHaveLength(MOVE_BATCH)
    expect(mockedAdopt.mock.calls[1][0].source_ids).toEqual(['s50', 's51', 's52'])
  })

  it('re-reads the rows when a later batch fails after an earlier one moved', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    const ids = Array.from({ length: MOVE_BATCH + 1 }, (_, i) => `s${i}`)
    const legacy = {
      provider: 'onshape',
      account_login: null,
      projects: [],
      source_ids: ids,
      claimable_connection_id: 'c1'
    }
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mockedAdopt
      .mockResolvedValueOnce({
        adopted: [{ connection_id: 'c1', provider: 'onshape', source_id: 's0', project_id: 'p' }],
        skipped: []
      })
      .mockRejectedValueOnce(new Error('500'))
    await act(async () => {
      expect(await result.current.move(legacy, ONSHAPE)).toBe(false)
    })
    expect(mockedList).toHaveBeenCalledTimes(2) // the partial move is on screen
  })
})

describe('useAccountConnections', () => {
  it('lists the linked accounts and revokes one, re-reading afterwards', async () => {
    mockedList.mockResolvedValueOnce([ONSHAPE]).mockResolvedValueOnce([])
    mockedRevoke.mockResolvedValue({ id: 'c1', disconnected_sources: 1 })
    const { result } = renderHook(() => useAccountConnections())

    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.connections).toEqual([ONSHAPE])

    let ok = false
    await act(async () => {
      ok = await result.current.revoke('c1')
    })
    expect(ok).toBe(true)
    expect(mockedRevoke).toHaveBeenCalledWith('c1')
    await waitFor(() => expect(result.current.connections).toEqual([]))
  })

  it('reports a failed revoke instead of pretending', async () => {
    mockedList.mockResolvedValue([ONSHAPE])
    mockedRevoke.mockRejectedValue(new Error('nope'))
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let ok = true
    await act(async () => {
      ok = await result.current.revoke('c1')
    })
    expect(ok).toBe(false)
  })

  it('is offline when fetching is disabled and never calls the API', async () => {
    vi.spyOn(online, 'useWorkspaceFetchEnabled').mockReturnValue(false)
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(mockedList).not.toHaveBeenCalled()
  })

  it('is offline when the API is unreachable', async () => {
    mockedList.mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useAccountConnections())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})

describe('linkedAccountFor', () => {
  it('finds only a CONNECTED account for the provider', () => {
    const errored = { ...ONSHAPE, id: 'c2', status: 'error' as const }
    expect(linkedAccountFor([errored, ONSHAPE], 'onshape')).toBe(ONSHAPE)
    expect(linkedAccountFor([errored], 'onshape')).toBeNull()
    expect(linkedAccountFor([ONSHAPE], 'github')).toBeNull()
  })
})
