// SOLUSDEV-320 P4-T3 — open findings grouped per subject: worst severity + count,
// one read per project load, refetched on the findings live key, never thrown.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Finding } from '../../lib/api/findings'
import * as findingsApi from '../../lib/api/findings'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'
import { findingsLiveKey, groupFindingsBySubject, useFindings } from './useFindings'

vi.mock('../../lib/api/findings', () => ({ listFindings: vi.fn() }))

const finding = (over: Partial<Finding>): Finding => ({
  id: 'f',
  rule_id: 'rule',
  severity: 'info',
  source: 'checker',
  status: 'open',
  headline: 'h',
  explanation: 'e',
  detail: null,
  subjects: ['e1'],
  evidence: {},
  count: 1,
  first_seen: '',
  last_seen: '',
  matrix_cell: null,
  domain: null,
  dismissed_until: null,
  created_at: '',
  updated_at: '',
  ...over
})

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
  useAuthStore.setState({ status: 'authenticated', accessToken: 't', user: { email: 'a@b.c' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'P' } })
})

describe('groupFindingsBySubject', () => {
  it('keeps the worst severity and counts every open finding touching a subject', () => {
    const grouped = groupFindingsBySubject([
      finding({ id: 'a', severity: 'warning', subjects: ['e1', 'e2'] }),
      finding({ id: 'b', severity: 'critical', subjects: ['e1'] }),
      finding({ id: 'c', severity: 'info', subjects: ['e1'] })
    ])
    expect(grouped.get('e1')).toEqual({ severity: 'critical', count: 3 })
    expect(grouped.get('e2')).toEqual({ severity: 'warning', count: 1 })
    expect(grouped.has('e3')).toBe(false)
  })
})

describe('useFindings', () => {
  it('reads open findings once per project and refetches on the live key', async () => {
    vi.mocked(findingsApi.listFindings).mockResolvedValue([finding({ severity: 'warning' })])
    const { result } = renderHook(() => useFindings('p1'))
    await waitFor(() => expect(result.current.bySubject.get('e1')?.count).toBe(1))
    expect(findingsApi.listFindings).toHaveBeenCalledExactlyOnceWith('p1', { status: 'open' })
    vi.mocked(findingsApi.listFindings).mockResolvedValue([])
    await bumpLive(findingsLiveKey('p1'))
    await waitFor(() => expect(result.current.bySubject.size).toBe(0))
    expect(findingsApi.listFindings).toHaveBeenCalledTimes(2)
  })

  it('yields an empty map on error and on manual refetch reads again', async () => {
    vi.mocked(findingsApi.listFindings).mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useFindings('p1'))
    await waitFor(() => expect(findingsApi.listFindings).toHaveBeenCalledTimes(1))
    expect(result.current.bySubject.size).toBe(0)
    vi.mocked(findingsApi.listFindings).mockResolvedValue([finding({})])
    act(() => result.current.refetch())
    await waitFor(() => expect(result.current.bySubject.get('e1')?.severity).toBe('info'))
  })

  it('never repopulates a stale project after switching', async () => {
    let release: (value: Finding[]) => void = () => undefined
    vi.mocked(findingsApi.listFindings).mockImplementation((id) =>
      id === 'p1'
        ? new Promise<Finding[]>((resolve) => {
            release = resolve
          })
        : Promise.resolve([])
    )
    const { result, rerender } = renderHook(({ id }) => useFindings(id), {
      initialProps: { id: 'p1' as string | null }
    })
    rerender({ id: 'p2' })
    await act(async () => {
      release([finding({ severity: 'critical' })])
    })
    expect(result.current.bySubject.size).toBe(0)
    rerender({ id: null })
    expect(result.current.bySubject.size).toBe(0)
  })
})
