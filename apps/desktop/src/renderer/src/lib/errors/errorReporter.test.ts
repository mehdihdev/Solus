// SOLUSDEV-311: the renderer's single error sink. One report per error object
// (a boundary and a global handler can both see the same error), main's ack
// decides whether it becomes a `client.error` data event (first sighting
// only, under a per-minute budget), dev builds echo to the console, and
// nothing here ever throws.
import { describe, it, expect, vi } from 'vitest'
import { createErrorReporter, type ErrorReporterDeps } from './errorReporter'
import type { DiagnosticsBridge } from '../desktopBridge'

const ACK = { fingerprint: '0123456789abcdef', first: true, appVersion: '1.0.0' }

function setup(overrides: Partial<ErrorReporterDeps> = {}): {
  reporter: ReturnType<typeof createErrorReporter>
  bridge: { report: ReturnType<typeof vi.fn>; takeCrashMarker: ReturnType<typeof vi.fn> }
  emit: ReturnType<typeof vi.fn>
  consoleError: ReturnType<typeof vi.fn>
} {
  const bridge = { report: vi.fn(async () => ACK), takeCrashMarker: vi.fn(async () => null) }
  const emit = vi.fn(async () => undefined)
  const consoleError = vi.fn()
  const reporter = createErrorReporter({
    bridge: () => bridge as unknown as DiagnosticsBridge,
    emitEvents: emit,
    projectId: () => 'p-1',
    isDev: false,
    consoleError,
    now: () => 0,
    ...overrides
  })
  return { reporter, bridge, emit, consoleError }
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('createErrorReporter', () => {
  it('sends a render error to main with its component stack', async () => {
    const { reporter, bridge } = setup()
    const error = new TypeError('boom')
    reporter.report(error, { origin: 'render', surface: 'bench', componentStack: '\n    at Bench' })
    await flush()
    expect(bridge.report).toHaveBeenCalledWith({
      origin: 'render',
      surface: 'bench',
      name: 'TypeError',
      message: 'boom',
      stack: error.stack,
      componentStack: '\n    at Bench'
    })
  })

  it('reports the same error object exactly once, whichever path sees it', async () => {
    const { reporter, bridge } = setup()
    const error = new Error('twice')
    reporter.report(error, { origin: 'render', surface: 'bench' })
    reporter.report(error, { origin: 'window_error', surface: 'root' })
    await flush()
    expect(bridge.report).toHaveBeenCalledTimes(1)
  })

  it('emits a client.error event on the first sighting, with no message or stack', async () => {
    const { reporter, emit } = setup()
    reporter.report(new RangeError('secret-ish detail'), { origin: 'render', surface: 'sol' })
    await flush()
    expect(emit).toHaveBeenCalledWith([
      {
        event_type: 'client.error',
        project_id: 'p-1',
        payload: {
          origin: 'render',
          surface: 'sol',
          error_name: 'RangeError',
          fingerprint: '0123456789abcdef',
          app_version: '1.0.0'
        }
      }
    ])
    expect(JSON.stringify(emit.mock.calls)).not.toContain('secret-ish')
  })

  it('does not emit an event when main says it has seen this fingerprint', async () => {
    const { reporter, emit, bridge } = setup()
    bridge.report.mockResolvedValue({ ...ACK, first: false })
    reporter.report(new Error('again'), { origin: 'render', surface: 'sol' })
    await flush()
    expect(emit).not.toHaveBeenCalled()
  })
})

describe('createErrorReporter — budgets, shapes and safety', () => {
  it('caps events per minute (a render loop cannot flood the event route)', async () => {
    const { reporter, emit } = setup()
    for (let i = 0; i < 25; i++)
      reporter.report(new Error(`e${i}`), { origin: 'render', surface: 'sol' })
    await flush()
    expect(emit).toHaveBeenCalledTimes(10)
  })

  it('maps an unknown error name to "other" and omits project_id when none is open', async () => {
    const { reporter, emit } = setup({ projectId: () => undefined })
    const error = new Error('x')
    error.name = 'WeirdCustomError'
    reporter.report(error, { origin: 'render', surface: 'sol' })
    await flush()
    const event = emit.mock.calls[0][0][0]
    expect(event.payload.error_name).toBe('other')
    expect(event).not.toHaveProperty('project_id')
  })

  it('reports a non-Error rejection reason as a bounded string', async () => {
    const { reporter, bridge } = setup()
    reporter.report({ weird: true }, { origin: 'unhandled_rejection', surface: 'root' })
    reporter.report('x'.repeat(5_000), { origin: 'unhandled_rejection', surface: 'root' })
    await flush()
    expect(bridge.report.mock.calls[0][0]).toMatchObject({
      name: 'Error',
      message: 'Non-Error value: object'
    })
    expect(bridge.report.mock.calls[1][0].message.length).toBeLessThanOrEqual(1_000)
  })

  it('echoes to the console in development only', async () => {
    const dev = setup({ isDev: true })
    dev.reporter.report(new Error('dev'), { origin: 'render', surface: 'sol' })
    expect(dev.consoleError).toHaveBeenCalledTimes(1)
    const prod = setup()
    prod.reporter.report(new Error('prod'), { origin: 'render', surface: 'sol' })
    expect(prod.consoleError).not.toHaveBeenCalled()
  })

  it('never throws — no bridge, a failing bridge, or a failing event post', async () => {
    const none = setup({ bridge: () => null })
    expect(() =>
      none.reporter.report(new Error('a'), { origin: 'render', surface: 'sol' })
    ).not.toThrow()
    const failing = setup({ emitEvents: vi.fn(async () => Promise.reject(new Error('401'))) })
    failing.reporter.report(new Error('b'), { origin: 'render', surface: 'sol' })
    await flush()
    expect(failing.bridge.report).toHaveBeenCalled()
  })
})

describe('reportPendingCrash', () => {
  it('turns the prior session crash into one client.error event', async () => {
    const { reporter, bridge, emit } = setup()
    bridge.takeCrashMarker.mockResolvedValue({
      origin: 'main_process',
      surface: 'main',
      errorName: 'TypeError',
      fingerprint: 'fedcba9876543210',
      appVersion: '1.0.0'
    })
    await reporter.reportPendingCrash()
    expect(emit).toHaveBeenCalledWith([
      {
        event_type: 'client.error',
        project_id: 'p-1',
        payload: {
          origin: 'main_process',
          surface: 'main',
          error_name: 'TypeError',
          fingerprint: 'fedcba9876543210',
          app_version: '1.0.0'
        }
      }
    ])
  })

  it('does nothing when there is no pending crash or no bridge', async () => {
    const { reporter, emit } = setup()
    await reporter.reportPendingCrash()
    expect(emit).not.toHaveBeenCalled()
    await expect(
      setup({ bridge: () => null }).reporter.reportPendingCrash()
    ).resolves.toBeUndefined()
  })
})
