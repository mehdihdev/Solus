// SOLUSDEV-72 — the device-keyed telemetry view. ONE batched poll per cycle
// for every visible device (per-device 1 Hz polling blew the shared 120/min
// rate budget); panels capped with an honest overflow line. Stream state
// derives from data timestamps — never asserted.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { DeviceBenchView, POLL_MS } from './DeviceBenchView'
import { BenchRealtimeContext } from './BenchRealtime'
import { getSignalAnomalies } from './signalAnomalies'
vi.mock('./signalAnomalies', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./signalAnomalies')>()),
  getSignalAnomalies: vi.fn(async () => [])
}))
import * as resources from '../../lib/api/resources'
import type { BenchDeviceRecent } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getBenchDeviceRecent: vi.fn() }
})

const mockedRecent = vi.mocked(resources.getBenchDeviceRecent)

function entry(deviceId: string): BenchDeviceRecent {
  return {
    device_id: deviceId,
    resolved_entity_id: null,
    signals: [{ signal: 'qvel', points: [{ timestamp: new Date().toISOString(), value: 1.25 }] }]
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getSignalAnomalies).mockResolvedValue([])
  useAuthStore.setState({ user: null })
  mockedRecent.mockImplementation(async (_p, deviceIds) => deviceIds.map(entry))
})

describe('DeviceBenchView', () => {
  it('resolves focus beyond the unfocused panel cap using bounded batches', async () => {
    const ids = Array.from({ length: 18 }, (_, index) => `device-${index}`)
    mockedRecent.mockImplementation(async (_project, batch) =>
      batch.includes('device-17') ? [entry('device-17')] : []
    )
    render(<DeviceBenchView projectId="p1" deviceIds={ids} focusEntityId="focus" />)
    expect(await screen.findByText('device-17')).toBeInTheDocument()
    expect(mockedRecent.mock.calls.every((call) => call[1].length <= 16)).toBe(true)
    expect(screen.queryByText(/more devices streaming/)).not.toBeInTheDocument()
  })

  it('hides the previous account feed before the new request resolves', async () => {
    useAuthStore.setState({ user: { email: 'first@example.test' } })
    render(<DeviceBenchView projectId="p1" deviceIds={['same-device']} />)
    expect(await screen.findByLabelText('qvel value')).toBeInTheDocument()
    mockedRecent.mockImplementation(() => new Promise(() => {}))
    act(() => useAuthStore.setState({ user: { email: 'second@example.test' } }))
    expect(screen.queryByLabelText('qvel value')).not.toBeInTheDocument()
  })

  it('does not show a previous project feed during a new project request', async () => {
    const view = render(<DeviceBenchView projectId="p1" deviceIds={['same-device']} />)
    expect(await screen.findByLabelText('qvel value')).toBeInTheDocument()
    mockedRecent.mockImplementation(() => new Promise(() => {}))
    view.rerender(<DeviceBenchView projectId="p2" deviceIds={['same-device']} />)
    expect(screen.queryByLabelText('qvel value')).not.toBeInTheDocument()
  })

  it('polls ONCE for all devices and renders a panel per device', async () => {
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod', 'demo/arm']} />)
    expect(await screen.findByText('demo/rod')).toBeInTheDocument()
    expect(screen.getByText('demo/arm')).toBeInTheDocument()
    await waitFor(() =>
      expect(mockedRecent).toHaveBeenCalledWith('p1', ['demo/arm', 'demo/rod'], { limit: 512 })
    )
    // One batched request, not one per device.
    expect(mockedRecent).toHaveBeenCalledTimes(1)
    expect((await screen.findAllByLabelText('qvel value')).length).toBe(2)
    // Fresh timestamps read as live — derived, not asserted.
    expect(screen.getAllByRole('region', { name: 'qvel signal' })).toHaveLength(2)
  })

  it('renders every observed device without an arbitrary panel cap', async () => {
    const many = Array.from({ length: 10 }, (_, i) => `dev/${i}`)
    render(<DeviceBenchView projectId="p1" deviceIds={many} />)
    await waitFor(() =>
      expect(mockedRecent).toHaveBeenCalledWith('p1', many, {
        limit: 512
      })
    )
    expect(await screen.findByText('dev/0')).toBeInTheDocument()
    expect(screen.getByText('dev/9')).toBeInTheDocument()
    expect(screen.getAllByRole('region', { name: 'qvel signal' })).toHaveLength(10)
  })

  it('says telemetry is unavailable when the poll fails — never fabricates', async () => {
    mockedRecent.mockRejectedValue(new Error('unreachable'))
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod']} />)
    expect(await screen.findByText(/Telemetry is unavailable for demo\/rod/)).toBeInTheDocument()
  })

  it('shows an honest empty line for a device with no recent values', async () => {
    mockedRecent.mockResolvedValue([
      { device_id: 'demo/rod', resolved_entity_id: null, signals: [] }
    ])
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod']} />)
    expect(await screen.findByText(/No recent values from demo\/rod/)).toBeInTheDocument()
  })
})

it('explains an unmapped focus and never falls back to all device telemetry', async () => {
  mockedRecent.mockResolvedValue([])
  render(<DeviceBenchView projectId="p1" deviceIds={['arm1', 'arm2']} focusEntityId="unrelated" />)
  expect(await screen.findByText(/No confirmed device mapping/)).toBeInTheDocument()
  expect(screen.queryByText('arm1')).not.toBeInTheDocument()
  expect(mockedRecent).toHaveBeenCalledWith('p1', ['arm1', 'arm2'], {
    limit: 512,
    focusEntityId: 'unrelated'
  })
})

it.each(['account', 'project'])('rejects telemetry after batched %s A→B→A', async (boundary) => {
  useAuthStore.setState({ user: { email: 'a@example.test' } })
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'A' } })
  let finish!: (value: BenchDeviceRecent[]) => void
  mockedRecent.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  mockedRecent.mockResolvedValue([])
  render(<DeviceBenchView projectId="p1" deviceIds={['expired-device']} focusEntityId="focus" />)
  await act(async () => {
    if (boundary === 'account') {
      useAuthStore.setState({ user: { email: 'b@example.test' } })
      useAuthStore.setState({ user: { email: 'a@example.test' } })
    } else {
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'B' } })
      useWorkspaceStore.setState({ project: { id: 'p1', name: 'A' } })
    }
    finish([entry('expired-device')])
  })
  expect(screen.queryByText('expired-device')).not.toBeInTheDocument()
})

it('fetches scoped observer evidence and clears it on project change', async () => {
  const at = new Date().toISOString()
  mockedRecent.mockResolvedValue([
    {
      device_id: 'd',
      resolved_entity_id: null,
      signals: [{ signal: 'qvel', points: [{ timestamp: at, value: 1 }] }]
    }
  ])
  vi.mocked(getSignalAnomalies).mockResolvedValue([
    { kind: 'stream_gap', device_id: 'd', signal: 'qvel', at, value: null }
  ])
  const view = render(<DeviceBenchView projectId="p1" deviceIds={['d']} />)
  expect(await screen.findByLabelText(`stream_gap at ${at}`)).toBeInTheDocument()
  vi.mocked(getSignalAnomalies).mockImplementation(() => new Promise(() => {}))
  mockedRecent.mockImplementation(() => new Promise(() => {}))
  view.rerender(<DeviceBenchView projectId="p2" deviceIds={['d']} />)
  expect(screen.queryByLabelText(`stream_gap at ${at}`)).not.toBeInTheDocument()
})

it('keeps signal values visible and reports unavailable anomaly evidence', async () => {
  vi.mocked(getSignalAnomalies).mockRejectedValue(new Error('offline'))
  render(<DeviceBenchView projectId="p1" deviceIds={['d']} />)
  expect(await screen.findByLabelText('qvel value')).toBeInTheDocument()
  expect(screen.getByText('Anomaly evidence is unavailable.')).toBeInTheDocument()
})

it('marks retained values stale after a failed poll instead of claiming healthy telemetry', async () => {
  vi.useFakeTimers()
  try {
    render(<DeviceBenchView projectId="p1" deviceIds={['d']} />)
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(screen.getByText('✓ Nothing out of range')).toBeInTheDocument()
    mockedRecent.mockRejectedValue(new Error('offline'))
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS))
    expect(screen.getByLabelText('qvel value')).toBeInTheDocument()
    expect(screen.queryByText('✓ Nothing out of range')).not.toBeInTheDocument()
    expect(screen.getByText(/Retained values are stale/)).toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

it('retains recent gap evidence for aged-out channels within the confirmed device scope', async () => {
  const at = new Date().toISOString()
  const device = entry('confirmed')
  device.signals[0].points[0].timestamp = new Date(Date.now() - 9000).toISOString()
  mockedRecent.mockResolvedValue([device])
  vi.mocked(getSignalAnomalies).mockResolvedValue([
    { kind: 'stream_gap', device_id: 'confirmed', signal: 'qvel', at, value: null },
    { kind: 'stream_gap', device_id: 'unmapped', signal: 'secret', at, value: null }
  ])
  render(
    <DeviceBenchView projectId="p1" deviceIds={['confirmed', 'unmapped']} focusEntityId="focus" />
  )
  expect(await screen.findByText('stream gap')).toBeInTheDocument()
  expect(screen.queryByLabelText('qvel value')).not.toBeInTheDocument()
  expect(screen.queryByText(/secret/)).not.toBeInTheDocument()
})

it('publishes fresh values while anomaly evidence is still pending', async () => {
  vi.mocked(getSignalAnomalies).mockImplementation(() => new Promise(() => {}))
  render(<DeviceBenchView projectId="p1" deviceIds={['arm']} />)
  expect(await screen.findByLabelText('qvel value')).toBeInTheDocument()
})

it('keeps an established signal visible and stale beyond the chart window', async () => {
  vi.useFakeTimers()
  const data = entry('arm')
  mockedRecent.mockResolvedValue([data])
  const view = render(<DeviceBenchView projectId="p1" deviceIds={['arm']} />)
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(screen.getByLabelText('qvel value')).toBeInTheDocument()
    expect(screen.getByText(/qvel.*STALE/)).toBeInTheDocument()
    view.rerender(<DeviceBenchView projectId="p1" deviceIds={[]} />)
    expect(screen.queryByLabelText('qvel value')).not.toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

it('does not clear values or repoll when device ordering changes', async () => {
  const view = render(<DeviceBenchView projectId="p1" deviceIds={['b', 'a']} />)
  await screen.findAllByLabelText('qvel value')
  mockedRecent.mockImplementation(() => new Promise(() => {}))
  const count = mockedRecent.mock.calls.length
  view.rerender(<DeviceBenchView projectId="p1" deviceIds={['a', 'b']} />)
  expect(screen.getAllByLabelText('qvel value')).toHaveLength(2)
  expect(mockedRecent.mock.calls.length).toBe(count)
})

it('uses shared live snapshots without telemetry or anomaly polling and masks revoked data', async () => {
  const device = entry('arm')
  const snapshot = {
    project: 'p1',
    ready: true,
    blocked: false,
    clock: Date.now(),
    receivedAt: Date.now(),
    devices: [device],
    focused: [device],
    events: [],
    eventsFailed: false
  }
  const view = render(
    <BenchRealtimeContext.Provider value={snapshot}>
      <DeviceBenchView projectId="p1" deviceIds={['arm']} />
    </BenchRealtimeContext.Provider>
  )
  expect(await screen.findByLabelText('qvel value')).toBeInTheDocument()
  expect(mockedRecent).not.toHaveBeenCalled()
  expect(getSignalAnomalies).not.toHaveBeenCalled()
  view.rerender(
    <BenchRealtimeContext.Provider
      value={{ ...snapshot, ready: false, blocked: true, devices: [], focused: [] }}
    >
      <DeviceBenchView projectId="p1" deviceIds={['arm']} />
    </BenchRealtimeContext.Provider>
  )
  expect(screen.queryByLabelText('qvel value')).not.toBeInTheDocument()
  expect(mockedRecent).not.toHaveBeenCalled()
})
