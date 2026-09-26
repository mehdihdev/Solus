import { expect, it, vi } from 'vitest'
import { benchSocketUrl, connectBenchStream, decodeBenchFrame } from './benchStream'
it('keeps proxy prefix and never puts credentials in the socket URL', () => {
  expect(benchSocketUrl('https://example.test/proxy/api/v1', 'session')).toBe(
    'wss://example.test/proxy/ws/v1/bench/sessions/session'
  )
  expect(benchSocketUrl('http://localhost:8000/api/v1/', 'session')).toBe(
    'ws://localhost:8000/ws/v1/bench/sessions/session'
  )
})
const frame = {
  type: 'telemetry',
  project_id: 'p',
  session_id: 's',
  devices: [
    {
      device_id: 'd',
      resolved_entity_id: 'entity',
      signals: [
        {
          signal: 'position',
          points: [{ timestamp: '2026-09-16T00:00:00Z', value: 1, unit: 'rad' }]
        }
      ]
    }
  ]
}
it('accepts bounded frames only for the requested project and session', () => {
  expect(decodeBenchFrame(JSON.stringify(frame), 'p', 's')[0].signals[0].points[0].unit).toBe('rad')
  expect(() => decodeBenchFrame(JSON.stringify(frame), 'other', 's')).toThrow()
  expect(() => decodeBenchFrame(JSON.stringify(frame), 'p', 'other')).toThrow()
  expect(() => decodeBenchFrame('invalid', 'p', 's')).toThrow()
  expect(() =>
    decodeBenchFrame(
      JSON.stringify({ ...frame, devices: [frame.devices[0], frame.devices[0]] }),
      'p',
      's'
    )
  ).toThrow()
})
it('rejects oversized or malformed data at the transport boundary', () => {
  expect(() => decodeBenchFrame(' '.repeat(4_194_305), 'p', 's')).toThrow()
  const bad = structuredClone(frame)
  bad.devices[0].signals[0].points[0].timestamp = 'invalid'
  expect(() => decodeBenchFrame(JSON.stringify(bad), 'p', 's')).toThrow()
})

class FakeSocket {
  static all: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => this.onclose?.({ code: 1006 }))
  constructor(readonly url: string) {
    FakeSocket.all.push(this)
  }
}
it('authenticates first, accepts heartbeats without samples, and cleans up retries', () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeSocket)
  FakeSocket.all = []
  const receive = vi.fn(),
    unavailable = vi.fn()
  try {
    const stop = connectBenchStream({
      baseUrl: 'http://localhost:8000/api/v1',
      project: 'p',
      session: 's',
      token: 'fixture-token',
      receive,
      unavailable
    })
    const socket = FakeSocket.all[0]
    socket.onopen?.()
    expect(socket.send).toHaveBeenCalledExactlyOnceWith(
      JSON.stringify({ type: 'authenticate', token: 'fixture-token', project_id: 'p' })
    )
    for (let i = 0; i < 5; i++) {
      vi.advanceTimersByTime(5000)
      socket.onmessage?.({
        data: JSON.stringify({ type: 'heartbeat', project_id: 'p', session_id: 's' })
      })
    }
    expect(receive).not.toHaveBeenCalled()
    expect(socket.close).not.toHaveBeenCalled()
    socket.onmessage?.({ data: JSON.stringify(frame) })
    expect(receive).toHaveBeenCalledOnce()
    socket.onclose?.({ code: 1006 })
    vi.advanceTimersByTime(1000)
    expect(FakeSocket.all).toHaveLength(2)
    stop()
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(2)
  } finally {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  }
})
it('fails closed on revoked access without reconnecting', () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeSocket)
  FakeSocket.all = []
  const unavailable = vi.fn()
  try {
    const stop = connectBenchStream({
      baseUrl: 'http://localhost:8000/api/v1',
      project: 'p',
      session: 's',
      token: 'fixture-token',
      receive: vi.fn(),
      unavailable
    })
    FakeSocket.all[0].onclose?.({ code: 4403 })
    expect(unavailable).toHaveBeenLastCalledWith(true)
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(1)
    stop()
  } finally {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  }
})
