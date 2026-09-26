// SOLUSDEV-311: boot wiring — crash handlers installed immediately, the log
// under the logs dir, the marker under userData, Sentry only with a DSN, and
// the two IPC channels registered against the real sender gates.
import { describe, it, expect, vi } from 'vitest'
import { bootDiagnostics, resolveSentryConfig, type BootDeps } from './boot'
import { DIAG_CHANNELS } from './diagnostics.constants'

function fakeDeps(): BootDeps & {
  handlers: Map<string, (event: { sender: unknown }, ...a: unknown[]) => unknown>
  procEvents: string[]
} {
  const handlers = new Map<string, (event: { sender: unknown }, ...a: unknown[]) => unknown>()
  const procEvents: string[] = []
  return {
    handlers,
    procEvents,
    app: {
      getPath: (name) => `/fake/${name}`,
      getVersion: () => '1.2.3',
      on: vi.fn(),
      relaunch: vi.fn(),
      exit: vi.fn()
    },
    proc: { on: (event) => void procEvents.push(event) },
    ipcMain: { handle: (channel, fn) => void handlers.set(channel, fn) },
    showErrorBox: vi.fn(),
    homeDir: '/Users/ada',
    isDev: true,
    ensureDir: vi.fn(),
    loadSentry: vi.fn(async () => null),
    sentry: { dsn: undefined, environment: 'development' }
  }
}

describe('bootDiagnostics', () => {
  it('installs process crash handlers at once', () => {
    const deps = fakeDeps()
    bootDiagnostics(deps)
    expect(deps.procEvents).toEqual(['uncaughtException', 'unhandledRejection'])
    expect(deps.app.on).toHaveBeenCalledWith('render-process-gone', expect.any(Function))
    expect(deps.ensureDir).toHaveBeenCalledWith('/fake/logs')
  })

  it('passes the DSN, release and environment to the Sentry loader', () => {
    const deps = { ...fakeDeps(), sentry: { dsn: 'https://k@o/1', environment: 'production' } }
    bootDiagnostics(deps)
    expect(deps.loadSentry).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'https://k@o/1',
        environment: 'production',
        release: 'solus-desktop@1.2.3',
        homeDir: '/Users/ada'
      })
    )
  })

  it('registers both channels behind the injected sender gates', () => {
    const deps = fakeDeps()
    bootDiagnostics(deps).registerIpc({
      isAppSender: (s) => s === 'app',
      isMainSender: () => false
    })
    const report = deps.handlers.get(DIAG_CHANNELS.report)!
    expect(report({ sender: 'other' }, {})).toBeNull()
    expect(
      report(
        { sender: 'app' },
        { origin: 'render', surface: 'bench', name: 'TypeError', message: 'boom' }
      )
    ).toMatchObject({ first: true, appVersion: '1.2.3' })
    expect(deps.handlers.get(DIAG_CHANNELS.takeCrashMarker)!({ sender: 'app' })).toBeNull()
  })
})

describe('resolveSentryConfig', () => {
  it('prefers a runtime SENTRY_DSN over the build-time MAIN_VITE_SENTRY_DSN', () => {
    expect(resolveSentryConfig({ SENTRY_DSN: 'a' }, { MAIN_VITE_SENTRY_DSN: 'b' }, false).dsn).toBe(
      'a'
    )
    expect(resolveSentryConfig({}, { MAIN_VITE_SENTRY_DSN: 'b' }, false).dsn).toBe('b')
    expect(resolveSentryConfig({}, {}, false).dsn).toBeUndefined()
  })

  it('defaults the environment from the build mode', () => {
    expect(resolveSentryConfig({}, {}, true).environment).toBe('development')
    expect(resolveSentryConfig({}, {}, false).environment).toBe('production')
    expect(
      resolveSentryConfig({}, { MAIN_VITE_SENTRY_ENVIRONMENT: 'staging' }, false).environment
    ).toBe('staging')
  })
})
