// SOLUSDEV-250 P3 — per-device proposal state: auto-propose in device order
// under an in-flight cap, skip ambiguous and bound devices, back off a silent
// device twice, keep failures verbatim, build the Add body exactly, turn a 409
// into a retarget offer, and forget everything on unmount.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../../store/authStore'
import { ApiError } from '../../../lib/api/envelope.types'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { useProjectFolderStore } from '../../project/projectFolderStore'
import { markAwaited, resetMarks } from '../../../lib/perf/marks'
import { resetDeviceProposals, useDeviceProposals } from './useDeviceProposals'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  proposeDetected: vi.fn(),
  confirmDetected: vi.fn(),
  acceptHardwareSuggestion: vi.fn()
}))

const device = (
  ref: string,
  extra: Partial<hardware.DetectedDeviceOut> = {}
): hardware.DetectedDeviceOut =>
  ({
    transport: 'usb_serial',
    device_ref: ref,
    identity: null,
    level: 'transport',
    board: null,
    board_class: 'usb_bridge',
    mcu_known: false,
    confidence: 0.4,
    evidence: [],
    ambiguous: false,
    last_seen_path: null,
    ...extra
  }) satisfies hardware.DetectedDeviceOut
const proposalFor = (ref: string, driver: string | null = 'serial_bus'): hardware.ProposalOut => ({
  device_ref: ref,
  level: 'protocol',
  summary: `1 device on ${ref}`,
  driver_id: driver,
  params: {},
  rows: [
    {
      id: `${ref}/1`,
      subject: 'M1 at 1',
      address: '1',
      model: 'M1',
      proposed_function: null,
      confidence: 0.9,
      evidence: [],
      provenance: 'bus'
    }
  ],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: []
})
const robot: Entity = {
  id: 'robot-1',
  type: 'physical_robot',
  domain: 'project',
  name: 'Rover',
  source_key: ''
}
type Deferred = { resolve: (p: hardware.ProposalOut) => void; reject: (e: unknown) => void }
function deferProposals(): Deferred[] {
  const pending: Deferred[] = []
  vi.mocked(hardware.proposeDetected).mockImplementation(
    () =>
      new Promise<hardware.ProposalOut>((resolve, reject) => {
        pending.push({ resolve, reject })
      })
  )
  return pending
}
const refsCalled = (): string[] => vi.mocked(hardware.proposeDetected).mock.calls.map((c) => c[1])

type Mounted = ReturnType<
  typeof renderHook<
    ReturnType<typeof useDeviceProposals>,
    { list: hardware.DetectedDeviceOut[]; graph: Entity[] | null }
  >
>
function mount(devices: hardware.DetectedDeviceOut[], entities: Entity[] | null = []): Mounted {
  return renderHook(
    ({ list, graph }: { list: hardware.DetectedDeviceOut[]; graph: Entity[] | null }) =>
      useDeviceProposals('p1', list, graph),
    { initialProps: { list: devices, graph: entities } }
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  resetDeviceProposals()
  useProjectFolderStore.setState({ folders: {} })
  vi.mocked(hardware.proposeDetected).mockImplementation((_p, ref) =>
    Promise.resolve(proposalFor(ref))
  )
})
afterEach(() => {
  resetMarks()
  performance.clearMarks()
  vi.useRealTimers()
})

describe('remounts and project switches', () => {
  // A stable list, as the device store provides one — a fresh array per render is a caller bug.
  const oneDevice = [device('usb:A')]
  const noEntities: Entity[] = []

  it('never proposes a device twice when the hook remounts while a request is in flight', async () => {
    const pending = deferProposals()
    const first = mount([device('usb:A')])
    expect(refsCalled()).toEqual(['usb:A'])
    first.unmount()
    const second = mount([device('usb:A')])
    expect(refsCalled()).toEqual(['usb:A'])
    await act(async () => {
      pending[0]?.resolve(proposalFor('usb:A'))
    })
    expect(second.result.current.cards[0]?.status).toBe('proposed')
  })

  it("never shows another project's proposal, not even for one render", async () => {
    const seen: string[] = []
    const view = renderHook(
      ({ projectId }: { projectId: string }) => {
        const proposals = useDeviceProposals(projectId, oneDevice, noEntities)
        for (const card of proposals.cards)
          if (card.proposal) seen.push(`${projectId}:${card.proposal.summary}`)
        return proposals
      },
      { initialProps: { projectId: 'p1' } }
    )
    await act(async () => {})
    expect(view.result.current.cards[0]?.proposal?.summary).toBe('1 device on usb:A')
    vi.mocked(hardware.proposeDetected).mockImplementation((_p, ref) =>
      Promise.resolve({ ...proposalFor(ref), summary: 'fresh for p2' })
    )
    view.rerender({ projectId: 'p2' })
    await act(async () => {})
    expect([...new Set(seen.filter((entry) => entry.startsWith('p2:')))]).toEqual([
      'p2:fresh for p2'
    ])
    expect(vi.mocked(hardware.proposeDetected).mock.calls.map((c) => c[0])).toEqual(['p1', 'p2'])
  })

  it('lets the new project propose a device whose old-project request was still in flight', async () => {
    const pending = deferProposals()
    const view = renderHook(
      ({ projectId }: { projectId: string }) =>
        useDeviceProposals(projectId, oneDevice, noEntities),
      { initialProps: { projectId: 'p1' } }
    )
    expect(refsCalled()).toEqual(['usb:A'])
    view.rerender({ projectId: 'p2' })
    await act(async () => {
      pending[0]?.resolve(proposalFor('usb:A'))
    })
    expect(vi.mocked(hardware.proposeDetected).mock.calls.map((c) => c[0])).toEqual(['p1', 'p2'])
    await act(async () => {
      pending[1]?.resolve({ ...proposalFor('usb:A'), summary: 'for p2' })
    })
    expect(view.result.current.cards[0]?.proposal?.summary).toBe('for p2')
  })
})

describe('auto-propose', () => {
  it('proposes in device order, at most two in flight, skipping ambiguous and bound devices', async () => {
    const pending = deferProposals()
    const { result } = mount(
      [
        device('usb_serial:BOUND'),
        device('usb_serial:A'),
        device('usb_serial:TWIN', { ambiguous: true }),
        device('usb_serial:B'),
        device('usb_serial:C')
      ],
      [{ ...robot, id: 'part', type: 'part', source_key: 'usb_serial:BOUND/1' }]
    )
    await act(async () => {})
    expect(refsCalled()).toEqual(['usb_serial:A', 'usb_serial:B'])
    expect(result.current.cards.map((c) => c.ref)).toEqual([
      'usb_serial:A',
      'usb_serial:TWIN',
      'usb_serial:B',
      'usb_serial:C'
    ])
    expect(result.current.cards[1]).toMatchObject({ status: 'failed', error: expect.any(String) })
    await act(async () => pending[0].resolve(proposalFor('usb_serial:A')))
    expect(refsCalled()).toEqual(['usb_serial:A', 'usb_serial:B', 'usb_serial:C'])
    expect(result.current.cards[0]).toMatchObject({ status: 'proposed', attempts: 1 })
    expect(hardware.proposeDetected).toHaveBeenCalledWith('p1', 'usb_serial:A')
  })

  it('never sends a private linked-folder path as repo_root', async () => {
    useProjectFolderStore.setState({ folders: { p1: { path: '/work/repo' } } })
    mount([device('usb_serial:A')])
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledWith('p1', 'usb_serial:A')
  })

  it('backs off a silent device 5 s then 15 s, then stops', async () => {
    vi.mocked(hardware.proposeDetected).mockImplementation((_p, ref) =>
      Promise.resolve(proposalFor(ref, null))
    )
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    expect(result.current.cards[0].status).toBe('silent')
    await act(async () => vi.advanceTimersByTime(4_999))
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(1)
    await act(async () => vi.advanceTimersByTime(1))
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(2)
    await act(async () => vi.advanceTimersByTime(15_000))
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(3)
    await act(async () => vi.advanceTimersByTime(60_000))
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(3)
    expect(result.current.cards[0]).toMatchObject({ status: 'silent', attempts: 3 })
  })

  it('keeps a failure verbatim and re-proposes on retry', async () => {
    vi.mocked(hardware.proposeDetected).mockRejectedValueOnce(new Error('runner absent: no bench'))
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    expect(result.current.cards[0]).toMatchObject({
      status: 'failed',
      error: 'runner absent: no bench'
    })
    act(() => result.current.retry('usb_serial:A'))
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(2)
    expect(result.current.cards[0].status).toBe('proposed')
  })

  it('drops a device that leaves the list, clearing its timer, and re-shows a dismissed one on re-plug', async () => {
    vi.mocked(hardware.proposeDetected).mockImplementation((_p, ref) =>
      Promise.resolve(proposalFor(ref, null))
    )
    const a = device('usb_serial:A')
    const { result, rerender } = mount([a, device('usb_serial:B')])
    await act(async () => {})
    act(() => result.current.dismiss('usb_serial:B'))
    expect(result.current.cards.map((c) => c.ref)).toEqual(['usb_serial:A'])
    rerender({ list: [], graph: [] })
    expect(result.current.cards).toEqual([])
    await act(async () => vi.advanceTimersByTime(30_000))
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(2)
    rerender({ list: [device('usb_serial:B')], graph: [] })
    expect(result.current.cards.map((c) => c.ref)).toEqual(['usb_serial:B'])
  })

  it('clears every timer on unmount', async () => {
    vi.mocked(hardware.proposeDetected).mockImplementation((_p, ref) =>
      Promise.resolve(proposalFor(ref, null))
    )
    const { unmount } = mount([device('usb_serial:A')])
    await act(async () => {})
    unmount()
    await act(async () => vi.advanceTimersByTime(30_000))
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(1)
  })
})

describe('confirm / accept', () => {
  const confirmed: hardware.ConfirmOut = {
    robot,
    part_ids: ['a'],
    config_entry_id: 'c',
    session_id: 's',
    session_error: null
  }

  it('sends defaults and the chosen config without a private folder path', async () => {
    vi.useRealTimers() // the fake clock replaces `performance`; the marks below need the real one
    useProjectFolderStore.setState({ folders: { p1: { path: '/work/repo' } } })
    vi.mocked(hardware.confirmDetected).mockResolvedValue(confirmed)
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    let out: hardware.ConfirmOut | null = null
    await act(async () => {
      out = await result.current.confirm('usb_serial:A', {
        name: 'Bench arm',
        target: { kind: 'new' },
        repoConfigId: 'c1'
      })
    })
    expect(hardware.confirmDetected).toHaveBeenCalledExactlyOnceWith('p1', 'usb_serial:A', {
      target: { kind: 'new', name: 'Bench arm' },
      accepted: [{ row_id: 'usb_serial:A/1', function_name: 'channel 1', category: 'actuators' }],
      repo_config_id: 'c1',
      start_session: true,
      window_seconds: 1
    })
    expect(out).toEqual(confirmed)
    expect(result.current.cards[0]).toMatchObject({ status: 'done', result: confirmed })
    // P6 marks: confirm_sent fired, and the robot's id is awaited by its card.
    expect(
      performance
        .getEntriesByType('mark')
        .filter((entry) => entry.name.startsWith('hw:confirm_sent:'))
    ).toHaveLength(1)
    expect(markAwaited('hw:node_visible', robot.id)).toBe(true)
  })

  it('omits optional fields when absent and never re-proposes once done', async () => {
    vi.mocked(hardware.confirmDetected).mockResolvedValue(confirmed)
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    await act(async () => {
      await result.current.confirm('usb_serial:A', {
        target: { kind: 'existing', robot_id: 'robot-1' }
      })
    })
    expect(hardware.confirmDetected).toHaveBeenCalledWith('p1', 'usb_serial:A', {
      target: { kind: 'existing', robot_id: 'robot-1' },
      accepted: expect.any(Array),
      start_session: true,
      window_seconds: 1
    })
    act(() => result.current.retry('usb_serial:A'))
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(1)
    expect(result.current.cards[0].status).toBe('done')
  })

  it('turns a 409 into a failed card naming the robot to retarget', async () => {
    vi.mocked(hardware.confirmDetected).mockRejectedValue(
      new ApiError(
        409,
        'conflict',
        'usb_serial:A/1 is already part of robot 0f9c2f2a-1111-4222-8333-444455556666 — reconnecting a known machine needs no second robot'
      )
    )
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    let out: hardware.ConfirmOut | null = confirmed
    await act(async () => {
      out = await result.current.confirm('usb_serial:A', { target: { kind: 'new', name: 'x' } })
    })
    expect(out).toBeNull()
    expect(result.current.cards[0]).toMatchObject({
      status: 'failed',
      error: expect.stringContaining('is already part of robot'),
      conflictRobotId: '0f9c2f2a-1111-4222-8333-444455556666'
    })
    expect(result.current.cards[0].proposal).not.toBeNull()
  })

  it('accepts a suggestion and marks the card done', async () => {
    vi.mocked(hardware.acceptHardwareSuggestion).mockResolvedValue({
      id: 'sug-1',
      subject_ref: 'usb_serial:A',
      subject_kind: 'device',
      candidate_robot_id: 'robot-1',
      confidence: 0.8,
      tier: 'high',
      evidence: [],
      reason: null,
      status: 'accepted',
      created_at: '',
      decided_at: null
    })
    const { result } = mount([device('usb_serial:A')])
    await act(async () => {})
    let ok = false
    await act(async () => {
      ok = await result.current.accept('usb_serial:A', 'sug-1')
    })
    expect(ok).toBe(true)
    expect(hardware.acceptHardwareSuggestion).toHaveBeenCalledExactlyOnceWith('p1', 'sug-1')
    expect(result.current.cards[0]).toMatchObject({ status: 'done', result: null })
  })

  it('shares one proposal state between two mounted consumers', async () => {
    const first = mount([device('usb_serial:A')])
    const second = mount([device('usb_serial:A')])
    await act(async () => {})
    expect(hardware.proposeDetected).toHaveBeenCalledTimes(1)
    expect(second.result.current.cards[0].status).toBe('proposed')
    act(() => first.result.current.dismiss('usb_serial:A'))
    expect(second.result.current.cards).toEqual([])
  })
})

it('expires proposal evidence across a same-project account A to B to A without reopening a busy port', async () => {
  act(() => useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.test' } }))
  const pending = deferProposals()
  const { result } = mount([device('usb:A')])
  act(() => {
    useAuthStore.setState({ user: { email: 'b@example.test' } })
    useAuthStore.setState({ user: { email: 'a@example.test' } })
  })
  expect(refsCalled()).toEqual(['usb:A'])
  await act(async () => pending[0]?.resolve(proposalFor('usb:A')))
  expect(result.current.cards[0]?.proposal).toBeNull()
  expect(refsCalled()).toEqual(['usb:A', 'usb:A'])
  await act(async () => pending[1]?.resolve(proposalFor('usb:A')))
  expect(result.current.cards[0]?.status).toBe('proposed')
})

it('does not publish a confirmation into a later account generation', async () => {
  let resolve!: (out: hardware.ConfirmOut) => void
  vi.mocked(hardware.confirmDetected).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const { result } = mount([device('usb:A')])
  await act(async () => {})
  let confirmation!: Promise<hardware.ConfirmOut | null>
  act(() => {
    confirmation = result.current.confirm('usb:A', { target: { kind: 'new' } })
  })
  act(() => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
  })
  await act(async () => {
    resolve({
      robot,
      part_ids: [],
      config_entry_id: 'fixture',
      session_id: null,
      session_error: null
    })
    expect(await confirmation).toBeNull()
  })
  expect(result.current.cards[0]?.result).toBeNull()
  expect(markAwaited('hw:node_visible', robot.id)).toBe(false)
})

it.each(['success', 'failure'])(
  'drops an old appearance probe %s after unplug and replug',
  async (outcome) => {
    const pending = deferProposals()
    const { result, rerender } = mount([device('usb:A')])
    rerender({ list: [], graph: [] })
    rerender({ list: [device('usb:A')], graph: [] })
    expect(refsCalled()).toEqual(['usb:A'])
    await act(async () => {
      if (outcome === 'success') pending[0]?.resolve(proposalFor('usb:A'))
      else pending[0]?.reject(new Error('old appearance failed'))
    })
    expect(result.current.cards[0]?.proposal).toBeNull()
    expect(result.current.cards[0]?.error).toBeNull()
    expect(refsCalled()).toEqual(['usb:A', 'usb:A'])
    await act(async () => pending[1]?.resolve(proposalFor('usb:A')))
    expect(result.current.cards[0]?.status).toBe('proposed')
  }
)

it('does not publish an old confirmation into a replugged appearance', async () => {
  let resolve!: (out: hardware.ConfirmOut) => void
  vi.mocked(hardware.confirmDetected).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const { result, rerender } = mount([device('usb:A')])
  await act(async () => {})
  let confirmation!: Promise<hardware.ConfirmOut | null>
  act(() => {
    confirmation = result.current.confirm('usb:A', { target: { kind: 'new' } })
  })
  rerender({ list: [], graph: [] })
  rerender({ list: [device('usb:A')], graph: [] })
  await act(async () => {
    resolve({
      robot,
      part_ids: [],
      config_entry_id: 'fixture',
      session_id: null,
      session_error: null
    })
    expect(await confirmation).toBeNull()
  })
  expect(result.current.cards[0]?.result).toBeNull()
})
