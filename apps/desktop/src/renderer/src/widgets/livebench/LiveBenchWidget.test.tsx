// LB-05: the Live Bench widget — focused-part telemetry, honest states, remount safety.
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Focus } from '@solus/shared-types'

import { LiveBenchWidget } from './LiveBenchWidget'
import { BenchRealtimeContext } from '../../features/bench/BenchRealtime'
import type { SignalSeriesOut } from './telemetry'
import { api } from '../../lib/api/client'
import { useAuthStore } from '../../store/authStore'

vi.mock('../../lib/api/client', () => ({
  api: { request: vi.fn(), requestPage: vi.fn() }
}))

const requestMock = vi.mocked(api.request)

const FOCUS: Focus = {
  entity: {
    projectId: '11111111-1111-1111-1111-111111111111',
    entityId: '22222222-2222-2222-2222-222222222222'
  },
  domain: 'runtime',
  label: 'elbow motor',
  path: []
}

function recentPayload(nowMs: number): unknown {
  return {
    entity_id: FOCUS.entity.entityId,
    signals: [
      {
        signal: 'rpm',
        points: [
          { timestamp: new Date(nowMs - 2000).toISOString(), value: 100 },
          { timestamp: new Date(nowMs - 1000).toISOString(), value: 140 }
        ]
      }
    ]
  }
}

function mockRoutes(recent: unknown, events: unknown = []): void {
  requestMock.mockImplementation((path: string) => {
    if (path.includes('/bench/telemetry-devices')) return Promise.resolve({ device_ids: [] })
    if (path.includes('/bench/sessions')) return Promise.resolve([])
    if (path.includes('/bench/recent/')) return Promise.resolve(recent)
    if (path.includes('/bench/events')) return Promise.resolve(events)
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => {
  requestMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('LiveBenchWidget', () => {
  registerTelemetryPresentationTests()

  registerTelemetryRecoveryTests()
})

function registerTelemetryPresentationTests(): void {
  it('renders the empty state and fetches nothing without a focus', () => {
    render(<LiveBenchWidget focus={null} onFocusChange={vi.fn()} />)

    expect(screen.getByRole('status').textContent).toMatch(
      /connected hardware appears automatically/i
    )
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('shows tiles, a chart, and a data-derived stream state when telemetry flows', async () => {
    mockRoutes(recentPayload(Date.now()))
    const states: string[] = []

    render(
      <LiveBenchWidget
        focus={FOCUS}
        onFocusChange={vi.fn()}
        onStateChange={(s) => states.push(s)}
      />
    )

    // The host state callback runs in an effect after the telemetry DOM commits.
    await waitFor(() => expect(states).toContain('ready'))
    expect(screen.getByTestId('signal-tiles').textContent).toContain('rpm: 140')
    expect(screen.getByTestId('chart-rpm').querySelectorAll('polyline').length).toBeGreaterThan(0)
    expect(screen.getByTestId('stream-state').textContent).toBe('LIVE DATA')
    expect(states).toContain('loading')
  })

  it('never labels anything REAL and shows no fake defaults', async () => {
    mockRoutes(recentPayload(Date.now()))
    render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByTestId('livebench-widget')).toBeInTheDocument())
    const text = screen.getByTestId('livebench-widget').textContent ?? ''
    expect(text).not.toMatch(/\bREAL\b/)
    expect(text).not.toMatch(/500 HZ/i)
  })

  it('does not attribute project-wide events without a confirmed device mapping', async () => {
    mockRoutes(recentPayload(Date.now()), [
      {
        kind: 'threshold_breach',
        device_id: 'motor-1',
        signal: 'temp',
        at: new Date().toISOString(),
        value: 95
      }
    ])

    render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByTestId('signal-tiles')).toBeInTheDocument())
    expect(screen.queryByTestId('anomaly-markers')).not.toBeInTheDocument()
  })

  it('shows an honest empty message when the part has no telemetry', async () => {
    mockRoutes({ entity_id: FOCUS.entity.entityId, signals: [] })

    render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/no telemetry yet/i))
  })
}

function registerTelemetryRecoveryTests(): void {
  it('reports the error state when the bench routes fail', async () => {
    requestMock.mockRejectedValue(new Error('api down'))
    const states: string[] = []

    render(
      <LiveBenchWidget
        focus={FOCUS}
        onFocusChange={vi.fn()}
        onStateChange={(s) => states.push(s)}
      />
    )

    // Wait on the STATE callback, not the DOM: `state` is derived during render,
    // so the alert is committed while `onStateChange` still fires in the effect
    // that follows. Waiting for the alert therefore resolves one tick early and
    // `states` is still ['loading'] — a real race that failed ~2 runs in 8.
    await waitFor(() => expect(states).toContain('error'))
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('is remount-safe: unmount stops the poll loop', async () => {
    vi.useFakeTimers()
    mockRoutes(recentPayload(Date.now()))

    const { unmount } = render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
    const callsBefore = requestMock.mock.calls.length
    unmount()
    await vi.advanceTimersByTimeAsync(5000)

    expect(requestMock.mock.calls.length).toBe(callsBefore)
  })
}

it('shows focused brain descendants with distinct device labels and scoped events', async () => {
  requestMock.mockImplementation(async (path: string) => {
    if (path.includes('/bench/telemetry-devices')) return { device_ids: ['a', 'b'] }
    if (path.includes('/bench/sessions')) return []
    if (path.includes('/bench/device-recent'))
      return {
        devices: ['a', 'b'].map((device_id) => ({
          device_id,
          resolved_entity_id: 'brain',
          signals: [
            {
              signal: 'position',
              points: [{ timestamp: new Date().toISOString(), value: device_id === 'a' ? 10 : 20 }]
            }
          ]
        }))
      }
    if (path.includes('/bench/events'))
      return ['a', 'unrelated'].map((device_id) => ({
        kind: 'threshold_breach',
        device_id,
        signal: 'position',
        at: new Date().toISOString(),
        value: 10
      }))
    if (path.includes('/bench/recent/')) return { entity_id: FOCUS.entity.entityId, signals: [] }
    throw new Error(path)
  })
  render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  await waitFor(() => expect(screen.getByTestId('signal-tiles')).toBeInTheDocument())
  expect(screen.getByTestId('signal-tiles')).toHaveTextContent('a · position: 10')
  expect(screen.getByTestId('signal-tiles')).toHaveTextContent('b · position: 20')
  expect(screen.getByTestId('anomaly-markers')).not.toHaveTextContent('unrelated')
  expect(
    requestMock.mock.calls.some(([path]) =>
      path.includes(`focus_entity_id=${FOCUS.entity.entityId}`)
    )
  ).toBe(true)
})

it('discards late telemetry after focus changes', async () => {
  let resolveOld!: (value: unknown) => void
  const pending = new Promise((resolve) => {
    resolveOld = resolve
  })
  requestMock.mockImplementation(async (path: string) => {
    if (path.includes('/bench/telemetry-devices')) return { device_ids: ['a'] }
    if (path.includes('/bench/events')) return []
    if (path.includes(`focus_entity_id=${FOCUS.entity.entityId}`)) return pending
    if (path.includes('/bench/device-recent')) return { devices: [] }
    throw new Error(path)
  })
  const { rerender } = render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  await waitFor(() =>
    expect(requestMock.mock.calls.some(([path]) => path.includes('/device-recent'))).toBe(true)
  )
  rerender(
    <LiveBenchWidget
      focus={{ ...FOCUS, entity: { ...FOCUS.entity, entityId: 'new' } }}
      onFocusChange={vi.fn()}
    />
  )
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('No telemetry yet'))
  resolveOld({
    devices: [
      {
        device_id: 'a',
        resolved_entity_id: 'old',
        signals: [{ signal: 'private-old', points: [] }]
      }
    ]
  })
  await waitFor(() => expect(screen.queryByText(/private-old/)).not.toBeInTheDocument())
})

it('hides rendered data immediately across an account epoch', async () => {
  mockRoutes(recentPayload(Date.now()))
  const { unmount } = render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  await screen.findByTestId('signal-tiles')
  const previous = useAuthStore.getState().status
  requestMock.mockImplementation(() => new Promise(() => {}))
  act(() =>
    useAuthStore.setState({ status: previous === 'loading' ? 'unauthenticated' : 'loading' })
  )
  expect(screen.queryByTestId('signal-tiles')).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Connecting')
  unmount()
  act(() => useAuthStore.setState({ status: previous }))
})

it('reports device-feed failure instead of an empty selection', async () => {
  requestMock.mockImplementation(async (path) => {
    if (path.includes('/telemetry-devices')) return { device_ids: ['a'] }
    if (path.includes('/events')) return []
    throw new Error('feed unavailable')
  })
  render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable')
  expect(screen.queryByText(/No telemetry yet/)).not.toBeInTheDocument()
})

it('charts current renamed channels instead of retained calibration-era signals', async () => {
  const now = Date.now()
  const series = (signal: string, age: number): SignalSeriesOut => ({
    signal,
    points: [{ timestamp: new Date(now - age).toISOString(), value: 1 }]
  })
  mockRoutes({
    entity_id: FOCUS.entity.entityId,
    signals: [
      ...Array.from({ length: 6 }, (_, i) => series(`Follower-Motor-${i}.position`, 600_000)),
      series('shoulder.position', 1000)
    ]
  })
  render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  await screen.findByTestId('signal-tiles')
  expect(screen.getByTestId('signal-tiles')).not.toHaveTextContent('Follower-Motor')
  expect(screen.getByTestId('chart-shoulder.position')).toBeInTheDocument()
  expect(screen.getByTestId('stream-state')).toHaveTextContent('LIVE DATA')
})

it('retains the stale feed honestly when no current channel exists', async () => {
  mockRoutes({
    entity_id: FOCUS.entity.entityId,
    signals: [
      {
        signal: 'shoulder.position',
        points: [{ timestamp: new Date(Date.now() - 10_000).toISOString(), value: 1 }]
      }
    ]
  })
  render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)
  await screen.findByTestId('signal-tiles')
  expect(screen.getByTestId('signal-tiles')).toHaveTextContent('shoulder.position')
  expect(screen.getByTestId('stream-state')).toHaveTextContent('STALE')
})

it('uses the shared focused stream without extra HTTP polls', async () => {
  const device = {
    device_id: 'arm',
    resolved_entity_id: 'brain',
    signals: [{ signal: 'joint', points: [{ timestamp: new Date().toISOString(), value: 2 }] }]
  }
  const snapshot = {
    project: FOCUS.entity.projectId,
    focusId: FOCUS.entity.entityId,
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
      <LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />
    </BenchRealtimeContext.Provider>
  )
  expect(screen.getByTestId('signal-tiles')).toHaveTextContent('arm · joint: 2')
  expect(requestMock).not.toHaveBeenCalled()
  view.rerender(
    <BenchRealtimeContext.Provider value={{ ...snapshot, clock: Date.now() + 10_000 }}>
      <LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />
    </BenchRealtimeContext.Provider>
  )
  expect(screen.getByTestId('stream-state')).toHaveTextContent('STALE')
  expect(requestMock).not.toHaveBeenCalled()
})
