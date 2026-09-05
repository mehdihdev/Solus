import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import * as resources from '../../lib/api/resources'
import * as online from './workspaceOnline'
import { linkedAccountFor, useAccountConnections } from './useAccountConnections'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, listConnections: vi.fn(), revokeConnection: vi.fn() }
})

const mockedList = vi.mocked(resources.listConnections)
const mockedRevoke = vi.mocked(resources.revokeConnection)

const ONSHAPE: resources.Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'ada@example.com',
  access: 'read',
  last_error: null,
  projects: [{ project_id: 'p1', name: 'Rover' }],
  created_at: '',
  updated_at: ''
}

beforeEach(() => {
  vi.spyOn(online, 'useWorkspaceFetchEnabled').mockReturnValue(true)
  mockedList.mockReset()
  mockedRevoke.mockReset()
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
