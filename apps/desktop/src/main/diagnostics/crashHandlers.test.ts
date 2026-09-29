// SOLUSDEV-311: main-process crash supervision. An uncaught exception is
// reported, marked for the next renderer, then the app relaunches — at most
// once per window; a second crash quits with a dialog. Dev never relaunches
// (electron-vite owns the process). Unhandled rejections are reported only.
// A renderer that dies (not a clean exit) is reported and marked.
import { describe, it, expect, vi } from 'vitest'
import { installCrashHandlers, type CrashHandlerDeps } from './crashHandlers'
import type { PendingCrash } from './diagnostics.constants'

type Listener = (...args: unknown[]) => void

function setup(overrides: Partial<CrashHandlerDeps> = {}): {
  deps: CrashHandlerDeps
  emitProcess: (event: string, ...args: unknown[]) => void
  emitApp: (event: string, ...args: unknown[]) => void
  recorded: PendingCrash[]
  settle: () => Promise<void>
} {
  const procListeners = new Map<string, Listener>()
  const appListeners = new Map<string, Listener>()
  const recorded: PendingCrash[] = []
  let pending: Promise<unknown> = Promise.resolve()
  const deps: CrashHandlerDeps = {
    proc: { on: (event, fn) => void procListeners.set(event, fn as Listener) },
    app: {
      on: (event, fn) => void appListeners.set(event, fn as Listener),
      relaunch: vi.fn(),
      exit: vi.fn()
    },
    diagnostics: {
      report: vi.fn(() => ({ fingerprint: '0123456789abcdef', first: true, appVersion: '1.0.0' })),
      flush: vi.fn(async () => undefined)
    },
    marker: {
      record: (c) => void recorded.push(c),
      mayRelaunch: vi.fn(() => true),
      markRelaunch: vi.fn(() => true)
    },
    showErrorBox: vi.fn(),
    now: () => 1_000,
    isDev: false,
    surfaceFor: () => 'root',
    track: (p) => {
      pending = p
    },
    ...overrides
  }
  installCrashHandlers(deps)
  return {
    deps,
    emitProcess: (event, ...args) => procListeners.get(event)?.(...args),
    emitApp: (event, ...args) => appListeners.get(event)?.(...args),
    recorded,
    settle: async () => {
      await pending
    }
  }
}

describe('installCrashHandlers', () => {
  it('reports an uncaught exception, marks it, flushes, then relaunches', async () => {
    const s = setup()
    s.emitProcess('uncaughtException', new TypeError('boom'))
    await s.settle()
    expect(s.deps.diagnostics.report).toHaveBeenCalledWith(
      expect.objectContaining({
        origin: 'main_process',
        surface: 'main',
        name: 'TypeError',
        message: 'boom'
      })
    )
    expect(s.recorded).toEqual([
      {
        origin: 'main_process',
        surface: 'main',
        errorName: 'TypeError',
        fingerprint: '0123456789abcdef',
        appVersion: '1.0.0'
      }
    ])
    expect(s.deps.diagnostics.flush).toHaveBeenCalled()
    expect(s.deps.marker.markRelaunch).toHaveBeenCalledWith(1_000)
    expect(s.deps.app.relaunch).toHaveBeenCalledTimes(1)
    expect(s.deps.app.exit).toHaveBeenCalledWith(1)
  })

  it('quits with a plain-language dialog instead of relaunching twice in the window', async () => {
    const s = setup({
      marker: { record: vi.fn(), mayRelaunch: () => false, markRelaunch: vi.fn(() => true) }
    })
    s.emitProcess('uncaughtException', new Error('again'))
    await s.settle()
    expect(s.deps.app.relaunch).not.toHaveBeenCalled()
    expect(s.deps.showErrorBox).toHaveBeenCalledWith(
      'Solus stopped',
      expect.stringContaining('restart Solus')
    )
    expect(s.deps.app.exit).toHaveBeenCalledWith(1)
  })

  it('fails closed when the loop guard cannot be saved (read-only / full disk)', async () => {
    const s = setup({
      marker: { record: vi.fn(), mayRelaunch: () => true, markRelaunch: vi.fn(() => false) }
    })
    s.emitProcess('uncaughtException', new Error('boom'))
    await s.settle()
    expect(s.deps.app.relaunch).not.toHaveBeenCalled()
    expect(s.deps.showErrorBox).toHaveBeenCalled()
    expect(s.deps.app.exit).toHaveBeenCalledWith(1)
  })

  it('in development: reports and exits, never relaunches', async () => {
    const s = setup({ isDev: true })
    s.emitProcess('uncaughtException', new Error('dev boom'))
    await s.settle()
    expect(s.deps.app.relaunch).not.toHaveBeenCalled()
    expect(s.deps.app.exit).toHaveBeenCalledWith(1)
  })

  it('a non-Error throw is still reported', async () => {
    const s = setup()
    s.emitProcess('uncaughtException', 'a string')
    await s.settle()
    expect(s.deps.diagnostics.report).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Error', message: 'a string' })
    )
  })

  it('a second exception while handling the first exits immediately', async () => {
    const s = setup()
    s.emitProcess('uncaughtException', new Error('one'))
    s.emitProcess('uncaughtException', new Error('two'))
    await s.settle()
    expect(s.deps.diagnostics.report).toHaveBeenCalledTimes(1)
    expect(s.deps.app.exit).toHaveBeenCalledWith(1)
  })
})

describe('installCrashHandlers — rejections and gone renderers', () => {
  it('an unhandled rejection is reported only — no marker, no relaunch', () => {
    const s = setup()
    s.emitProcess('unhandledRejection', new RangeError('late'))
    expect(s.deps.diagnostics.report).toHaveBeenCalledWith(
      expect.objectContaining({ origin: 'main_process', name: 'RangeError' })
    )
    expect(s.recorded).toHaveLength(0)
    expect(s.deps.app.relaunch).not.toHaveBeenCalled()
  })

  it('a crashed renderer is reported and marked with its window surface', () => {
    const s = setup({ surfaceFor: () => 'sol_window' })
    s.emitApp('render-process-gone', {}, {}, { reason: 'crashed', exitCode: 11 })
    expect(s.deps.diagnostics.report).toHaveBeenCalledWith({
      origin: 'renderer_gone',
      surface: 'sol_window',
      name: 'RendererGone',
      message: 'reason=crashed exitCode=11'
    })
    expect(s.recorded[0]).toMatchObject({
      origin: 'renderer_gone',
      surface: 'sol_window',
      errorName: 'other'
    })
  })

  it('a clean renderer exit is not an error', () => {
    const s = setup()
    s.emitApp('render-process-gone', {}, {}, { reason: 'clean-exit', exitCode: 0 })
    expect(s.deps.diagnostics.report).not.toHaveBeenCalled()
  })
})
