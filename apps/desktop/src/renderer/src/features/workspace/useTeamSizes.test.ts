// SOLUSDEV-319 (multi-team Home): each of my teams' member count for the team rail,
// read once per team id; a team whose detail fails simply shows no count.
import { renderHook, waitFor } from '@testing-library/react'
import { StrictMode, createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useTeamSizes } from './useTeamSizes'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  getTeamDetail: vi.fn()
}))

function detail(id: string, members: number): resources.TeamDetail {
  return {
    id,
    name: id,
    is_personal: false,
    plan_status: 'active',
    settings: { notify_project_created: true },
    created_at: '',
    member_count: members,
    role: 'member'
  }
}

beforeEach(() => {
  vi.mocked(resources.getTeamDetail)
    .mockReset()
    .mockImplementation(async (id: string) => {
      if (id === 'broken') throw new Error('offline')
      return detail(id, id === 'a' ? 4 : 12)
    })
})

describe('useTeamSizes', () => {
  it('reads each team once and maps it to its member count', async () => {
    const { result, rerender } = renderHook(({ ids }) => useTeamSizes(ids), {
      initialProps: { ids: ['a', 'b'] }
    })
    await waitFor(() => expect(result.current).toEqual({ a: 4, b: 12 }))

    rerender({ ids: ['a', 'b'] })
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(2)
  })

  it('reads only a team that is new to the list', async () => {
    const { result, rerender } = renderHook(({ ids }) => useTeamSizes(ids), {
      initialProps: { ids: ['a'] }
    })
    await waitFor(() => expect(result.current).toEqual({ a: 4 }))
    rerender({ ids: ['a', 'b'] })
    await waitFor(() => expect(result.current).toEqual({ a: 4, b: 12 }))
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(2)
  })

  it('leaves out a team whose detail could not be read', async () => {
    const { result } = renderHook(() => useTeamSizes(['a', 'broken']))
    await waitFor(() => expect(result.current).toEqual({ a: 4 }))
  })

  it('can refresh one team after its roster changed', async () => {
    const { result } = renderHook(() => useTeamSizes(['a'], { a: 5 }))
    await waitFor(() => expect(result.current.a).toBe(5))
  })
  it('fills sizes under StrictMode, whose first effect run is thrown away', async () => {
    const wrapper = ({ children }: { children: ReactNode }): React.JSX.Element =>
      createElement(StrictMode, null, children)
    const { result } = renderHook(() => useTeamSizes(['a', 'b']), { wrapper })
    await waitFor(() => expect(result.current).toEqual({ a: 4, b: 12 }))
  })
  it('never asks twice for a team, even while another one lands or after a failure', async () => {
    let releaseB: (d: resources.TeamDetail) => void = () => undefined
    vi.mocked(resources.getTeamDetail).mockImplementation(async (id: string) => {
      if (id === 'b') return new Promise((resolve) => (releaseB = resolve))
      if (id === 'broken') throw new Error('offline')
      return detail(id, 4)
    })
    const { result } = renderHook(() => useTeamSizes(['a', 'b', 'broken']))
    await waitFor(() => expect(result.current).toEqual({ a: 4 }))
    releaseB(detail('b', 12))
    await waitFor(() => expect(result.current).toEqual({ a: 4, b: 12 }))
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(3)
  })
})
