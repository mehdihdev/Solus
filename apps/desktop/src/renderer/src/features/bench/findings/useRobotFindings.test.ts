// SOLUSDEV-321 P2-T7 — the Findings pane's data: one open-findings read per connected robot,
// refetched on the findings live key (never a second stream, never a poll), and an error that
// reads as "unavailable", never as "nothing out of range".
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import type { Finding } from '../../../lib/api/findings'
import * as findingsApi from '../../../lib/api/findings'
import type { BenchSession } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { resetLiveRevisions } from '../../../store/liveRevisionStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { findingsLiveKey } from '../../graph/useFindings'
import { bumpLive } from '../../live/testBump'
import {
  connectedRobots,
  loadMissingSignals,
  severityGroups,
  useRobotFindings,
  useSelectedFinding
} from './useRobotFindings'

vi.mock('../../../lib/api/findings', () => ({ listFindings: vi.fn(), getFinding: vi.fn() }))
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn(), requestPage: vi.fn() } }))

const finding = (over: Partial<Finding>): Finding => ({
  id: 'f',
  rule_id: 'rule',
  severity: 'warning',
  source: 'observer',
  status: 'open',
  headline: 'h',
  explanation: '',
  detail: '',
  subjects: ['e1'],
  evidence: {},
  count: 1,
  first_seen: '2026-10-27T10:00:00+00:00',
  last_seen: '2026-10-27T10:00:00+00:00',
  matrix_cell: null,
  domain: 'electrical',
  dismissed_until: null,
  created_at: '',
  updated_at: '',
  ...over
})

const session = (over: Partial<BenchSession>): BenchSession => ({
  id: 's',
  mode: 'real',
  provider: 'robot',
  status: 'active',
  link: 'streaming',
  label: 'Fake arm',
  created_at: '',
  ended_at: null,
  device: null,
  device_ids: [],
  counts: { ingested: 0, unresolved: 0 },
  last_summary: null,
  ...over
})

const ROBOTS = [{ robotId: 'r1', label: 'Fake arm' }]

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
  useAuthStore.setState({ status: 'authenticated', accessToken: null, user: { email: 'a@b.c' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'P' } })
})

describe('connectedRobots', () => {
  it('lists each live robot session once, by the robot it observes', () => {
    expect(
      connectedRobots([
        session({ id: 's1', robot_entity_id: 'r1', label: 'Fake arm' }),
        session({ id: 's2', robot_entity_id: 'r1', label: 'Fake arm again' }),
        session({ id: 's3', robot_entity_id: 'r2', status: 'ended' }),
        session({ id: 's4', mode: 'sim', provider: 'mujoco', robot_entity_id: null }),
        session({ id: 's5', robot_entity_id: 'r3', label: 'Bench part', status: 'starting' })
      ])
    ).toEqual([
      { robotId: 'r1', label: 'Fake arm' },
      { robotId: 'r3', label: 'Bench part' }
    ])
    expect(connectedRobots(null)).toEqual([])
  })
})

describe('severityGroups', () => {
  it('orders critical, warning, info with each count and the newest last seen', () => {
    const groups = severityGroups([
      finding({ id: 'w1', last_seen: '2026-10-27T10:00:05+00:00' }),
      finding({ id: 'i1', severity: 'info', source: 'checker' }),
      finding({ id: 'c1', severity: 'critical', last_seen: '2026-10-27T10:00:01+00:00' }),
      finding({ id: 'w2', last_seen: '2026-10-27T10:00:09+00:00' })
    ])
    expect(groups.map((g) => [g.severity, g.count, g.lastSeen])).toEqual([
      ['critical', 1, '2026-10-27T10:00:01+00:00'],
      ['warning', 2, '2026-10-27T10:00:09+00:00'],
      ['info', 1, '2026-10-27T10:00:00+00:00']
    ])
    expect(groups[1].findings.map((f) => f.id)).toEqual(['w1', 'w2'])
    expect(severityGroups([])).toEqual([])
  })
})

describe('useRobotFindings', () => {
  it('reads open findings per connected robot and refetches on the findings live key', async () => {
    vi.mocked(findingsApi.listFindings).mockResolvedValue([finding({ id: 'f1' })])
    const { result } = renderHook(() =>
      useRobotFindings('p1', [...ROBOTS, { robotId: 'r2', label: 'Second arm' }])
    )
    await waitFor(() => expect(result.current.groups[0].status).toBe('ready'))
    expect(findingsApi.listFindings).toHaveBeenCalledWith('p1', { status: 'open', robot: 'r1' })
    expect(findingsApi.listFindings).toHaveBeenCalledWith('p1', { status: 'open', robot: 'r2' })
    expect(result.current.groups.map((g) => [g.label, g.findings.map((f) => f.id)])).toEqual([
      ['Fake arm', ['f1']],
      ['Second arm', ['f1']]
    ])
    vi.mocked(findingsApi.listFindings).mockResolvedValue([])
    await bumpLive(findingsLiveKey('p1'))
    await waitFor(() => expect(result.current.groups[0].findings).toEqual([]))
    expect(findingsApi.listFindings).toHaveBeenCalledTimes(4)
    act(() => result.current.refetch())
    await waitFor(() => expect(findingsApi.listFindings).toHaveBeenCalledTimes(6))
  })

  it('reads a failed read as unavailable, never as an empty robot', async () => {
    vi.mocked(findingsApi.listFindings).mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useRobotFindings('p1', ROBOTS))
    await waitFor(() => expect(result.current.groups[0].status).toBe('failed'))
    expect(result.current.groups[0].findings).toEqual([])
  })

  it('asks nothing without a connected robot and never repopulates a stale project', async () => {
    const { result, rerender } = renderHook(({ id, robots }) => useRobotFindings(id, robots), {
      initialProps: { id: 'p1' as string | null, robots: [] as typeof ROBOTS }
    })
    expect(result.current.groups).toEqual([])
    expect(findingsApi.listFindings).not.toHaveBeenCalled()
    let release: (value: Finding[]) => void = () => undefined
    vi.mocked(findingsApi.listFindings).mockImplementation((id) =>
      id === 'p1'
        ? new Promise<Finding[]>((resolve) => {
            release = resolve
          })
        : Promise.resolve([])
    )
    rerender({ id: 'p1', robots: ROBOTS })
    rerender({ id: 'p2', robots: ROBOTS })
    await act(async () => release([finding({ severity: 'critical' })]))
    await waitFor(() => expect(result.current.groups[0].status).toBe('ready'))
    expect(result.current.groups[0].findings).toEqual([])
  })
})

describe('useSelectedFinding', () => {
  it('reads the opened finding and refreshes it on the live key', async () => {
    vi.mocked(findingsApi.getFinding).mockResolvedValue(finding({ id: 'f9', count: 1 }))
    const { result, rerender } = renderHook(({ id }) => useSelectedFinding('p1', id), {
      initialProps: { id: null as string | null }
    })
    expect(result.current).toEqual({ finding: null, failed: false })
    expect(findingsApi.getFinding).not.toHaveBeenCalled()
    rerender({ id: 'f9' })
    await waitFor(() => expect(result.current.finding?.id).toBe('f9'))
    expect(findingsApi.getFinding).toHaveBeenCalledWith('p1', 'f9')
    vi.mocked(findingsApi.getFinding).mockResolvedValue(finding({ id: 'f9', count: 4 }))
    await bumpLive(findingsLiveKey('p1'))
    await waitFor(() => expect(result.current.finding?.count).toBe(4))
    vi.mocked(findingsApi.getFinding).mockRejectedValue(new Error('gone'))
    rerender({ id: 'f10' })
    await waitFor(() => expect(result.current).toEqual({ finding: null, failed: true }))
  })
})

describe('loadMissingSignals', () => {
  it("reads the robot's missing_signals on request, as text, bounded", async () => {
    vi.mocked(api.request).mockResolvedValueOnce({
      properties: { missing_signals: ['servo 2: temperature', 7, 'servo 5: stall_current_a'] }
    })
    expect(await loadMissingSignals('p1', 'r1')).toEqual([
      'servo 2: temperature',
      'servo 5: stall_current_a'
    ])
    expect(api.request).toHaveBeenCalledWith('/projects/p1/entities/r1')
    vi.mocked(api.request).mockResolvedValueOnce({ properties: {} })
    expect(await loadMissingSignals('p1', 'r1')).toBeNull()
    vi.mocked(api.request).mockResolvedValueOnce({
      properties: { missing_signals: Array(500).fill('x') }
    })
    expect(await loadMissingSignals('p1', 'r1')).toHaveLength(200)
  })
})
