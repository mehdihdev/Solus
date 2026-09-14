// LB-05: the Live Bench widget — focused-part telemetry, honest states, remount safety.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Focus } from '@solus/shared-types'

import { LiveBenchWidget } from './LiveBenchWidget'
import { api } from '../../lib/api/client'

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

    expect(screen.getByRole('status').textContent).toMatch(/focus a part/i)
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

    await waitFor(() => expect(screen.getByTestId('signal-tiles')).toBeInTheDocument())
    expect(screen.getByTestId('signal-tiles').textContent).toContain('rpm: 140')
    expect(screen.getByTestId('chart-rpm').querySelectorAll('polyline').length).toBeGreaterThan(0)
    expect(screen.getByTestId('stream-state').textContent).toBe('LIVE DATA')
    expect(states).toContain('loading')
    expect(states).toContain('ready')
  })

  it('never labels anything REAL and shows no fake defaults', async () => {
    mockRoutes(recentPayload(Date.now()))
    render(<LiveBenchWidget focus={FOCUS} onFocusChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByTestId('livebench-widget')).toBeInTheDocument())
    const text = screen.getByTestId('livebench-widget').textContent ?? ''
    expect(text).not.toMatch(/\bREAL\b/)
    expect(text).not.toMatch(/500 HZ/i)
  })

  it('renders observer events as anomaly markers', async () => {
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

    await waitFor(() => expect(screen.getByTestId('anomaly-markers')).toBeInTheDocument())
    expect(screen.getByTestId('anomaly-markers').textContent).toContain('threshold_breach')
    expect(screen.getByTestId('anomaly-markers').textContent).toContain('temp')
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
