// SOLUSDEV-311: the main-only Sentry sink. No DSN → no SDK load at all. With a
// DSN: PII off, no breadcrumbs, only an allowlisted set of integrations (no
// minidumps, local variables, console/net capture, screenshots or the SDK's own
// uncaught handlers), and every outgoing event re-scrubbed.
import { describe, it, expect, vi } from 'vitest'
import { loadSentrySink, KEPT_INTEGRATIONS, type SentryModule } from './sentrySink'

type Init = Parameters<SentryModule['init']>[0]

function fakeSentry(): SentryModule & { initOptions: () => Init } {
  let options: Init | undefined
  return {
    init: vi.fn((o: Init) => {
      options = o
    }),
    captureException: vi.fn(),
    flush: vi.fn(async () => true),
    IPCMode: { Classic: 1 },
    initOptions: () => options!
  }
}

function fakeIpc(): {
  removeAllListeners: ReturnType<typeof vi.fn>
  removeHandler: ReturnType<typeof vi.fn>
} {
  return { removeAllListeners: vi.fn(), removeHandler: vi.fn() }
}

const BASE = {
  environment: 'development',
  release: 'solus-desktop@1.0.0',
  homeDir: '/Users/ada',
  ipc: fakeIpc()
}

describe('loadSentrySink', () => {
  it('returns null and never loads the SDK when no DSN is configured', async () => {
    const load = vi.fn()
    expect(await loadSentrySink({ ...BASE, dsn: undefined, load })).toBeNull()
    expect(await loadSentrySink({ ...BASE, dsn: '  ', load })).toBeNull()
    expect(load).not.toHaveBeenCalled()
  })

  it('initialises with PII off, classic IPC, no tracing setup and no breadcrumbs', async () => {
    const sentry = fakeSentry()
    await loadSentrySink({
      ...BASE,
      dsn: 'https://k@o1.ingest.sentry.io/1',
      load: async () => sentry
    })
    const o = sentry.initOptions()
    expect(o).toMatchObject({
      dsn: 'https://k@o1.ingest.sentry.io/1',
      sendDefaultPii: false,
      ipcMode: 1,
      skipOpenTelemetrySetup: true,
      environment: 'development',
      release: 'solus-desktop@1.0.0'
    })
    expect(o.beforeBreadcrumb()).toBeNull()
  })

  it("tears down the SDK's own renderer IPC channels (no renderer may feed Sentry directly)", async () => {
    const sentry = fakeSentry()
    const ipc = fakeIpc()
    await loadSentrySink({ ...BASE, ipc, dsn: 'https://k@o/1', load: async () => sentry })
    const ns = (sentry.initOptions() as unknown as { ipcNamespace: string }).ipcNamespace
    expect(ns).toMatch(/^sentry-ipc-[0-9a-f-]{36}$/)
    const removed = ipc.removeAllListeners.mock.calls.map(([channel]) => channel)
    for (const ch of ['start', 'scope', 'envelope', 'structured-log', 'metric', 'status']) {
      expect(removed).toContain(`${ns}.${ch}`)
    }
    expect(ipc.removeHandler).toHaveBeenCalledWith(`${ns}.feedback`)
  })

  it('uses a fresh IPC namespace per launch', async () => {
    const a = fakeSentry()
    const b = fakeSentry()
    await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => a })
    await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => b })
    const ns = (s: ReturnType<typeof fakeSentry>): string =>
      (s.initOptions() as unknown as { ipcNamespace: string }).ipcNamespace
    expect(ns(a)).not.toBe(ns(b))
  })

  it('keeps no offline queue and never flushes one at startup (consent is unknown then)', async () => {
    const sentry = fakeSentry()
    await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => sentry })
    const t = (
      sentry.initOptions() as unknown as {
        transportOptions: { flushAtStartup: boolean; shouldStore: () => boolean }
      }
    ).transportOptions
    expect(t.flushAtStartup).toBe(false)
    expect(t.shouldStore()).toBe(false)
  })

  it('keeps only allowlisted integrations', async () => {
    const sentry = fakeSentry()
    await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => sentry })
    const names = [
      'SentryMinidump',
      'LocalVariables',
      'Console',
      'Screenshots',
      'OnUncaughtException',
      'ElectronContext',
      'LinkedErrors'
    ]
    const kept = sentry
      .initOptions()
      .integrations(names.map((name) => ({ name })))
      .map((i) => i.name)
    expect(kept).toEqual(['ElectronContext', 'LinkedErrors'])
    expect(KEPT_INTEGRATIONS.has('SentryMinidump')).toBe(false)
  })
})

describe('loadSentrySink event handling', () => {
  it('beforeSend strips user/request/server and re-scrubs exception text', async () => {
    const sentry = fakeSentry()
    await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => sentry })
    const event = {
      user: { id: 'u' },
      request: { url: 'x' },
      server_name: 'adas-mac',
      message: 'hi ada@example.com',
      exception: { values: [{ type: 'TypeError', value: 'at /Users/ada/x.js' }] }
    }
    const out = sentry.initOptions().beforeSend(event)
    expect(out).not.toHaveProperty('user')
    expect(out).not.toHaveProperty('request')
    expect(out).not.toHaveProperty('server_name')
    expect(out.message).toBe('hi [email]')
    expect(out.exception.values[0].value).toBe('at ~/x.js')
  })

  it('captures with the fingerprint, origin/surface tags and the component stack', async () => {
    const sentry = fakeSentry()
    const sink = await loadSentrySink({ ...BASE, dsn: 'https://k@o/1', load: async () => sentry })
    sink!.capture({
      origin: 'render',
      surface: 'bench',
      name: 'TypeError',
      message: 'boom',
      stack: 'TypeError: boom\n    at X',
      componentStack: '\n    at BenchScreen',
      fingerprint: '0123456789abcdef'
    })
    const [error, hint] = (sentry.captureException as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(error).toMatchObject({
      name: 'TypeError',
      message: 'boom',
      stack: 'TypeError: boom\n    at X'
    })
    expect(hint).toEqual({
      fingerprint: ['0123456789abcdef'],
      tags: { origin: 'render', surface: 'bench' },
      contexts: { react: { componentStack: '\n    at BenchScreen' } }
    })
  })

  it('returns null (and does not throw) when the SDK fails to load', async () => {
    const sink = await loadSentrySink({
      ...BASE,
      dsn: 'https://k@o/1',
      load: async () => {
        throw new Error('missing module')
      }
    })
    expect(sink).toBeNull()
  })
})
