// @vitest-environment node
// SOLUSDEV-320 P5-T1d: the machine reporter — MAIN tells the API which machine
// this companion runs on (PUT …/members/me/machines/{companion_id}) and
// mirrors the shared-flagged preferences (PUT …/members/me/preferences).
// Deps-injected and timer-driven: no network, no clock, no disk.
import { describe, expect, it, vi } from 'vitest'
import {
  MACHINE_REPORT_DEBOUNCE_MS,
  startMachineReporter,
  type MachineReporterDeps
} from './machineReport'

const PROJECT = '2b1f2a3c-4d5e-4f60-8a71-9b8c7d6e5f40'
const COMPANION = 'a'.repeat(32)

interface Harness {
  deps: MachineReporterDeps
  calls: Array<{ url: string; init: RequestInit }>
  timers: Array<{ fn: () => void; ms: number; cancelled: boolean }>
  clock: { now: number }
  platform: { os: string; arch: string; hostname: string }
  identity: { id: string; name: string } | null
  respond: { ok: boolean }
}

function harness(over: Partial<Pick<Harness, 'identity' | 'platform'>> = {}): Harness {
  const h: Harness = {
    calls: [],
    timers: [],
    clock: { now: 1_000 },
    platform: over.platform ?? { os: 'linux', arch: 'arm64', hostname: 'bench-1' },
    identity: 'identity' in over ? (over.identity ?? null) : { id: COMPANION, name: 'bench-1' },
    respond: { ok: true },
    deps: undefined as unknown as MachineReporterDeps
  }
  h.deps = {
    fetcher: vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      h.calls.push({ url: String(url), init: init ?? {} })
      return new Response(null, { status: h.respond.ok ? 200 : 500 })
    }) as unknown as typeof fetch,
    identity: () => h.identity,
    platform: () => h.platform,
    now: () => h.clock.now,
    schedule: (fn, ms) => {
      const timer = { fn, ms, cancelled: false }
      h.timers.push(timer)
      return () => {
        timer.cancelled = true
      }
    },
    apiBaseUrl: 'https://api.solus.test/api/v1'
  }
  return h
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setImmediate(resolve))
}

function fireTimers(h: Harness): void {
  const due = h.timers.filter((t) => !t.cancelled)
  h.timers = []
  for (const t of due) t.fn()
}

describe('machine lane', () => {
  it('first project open with a token sends one PUT with the machine body', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(1)
    const [{ url, init }] = h.calls
    expect(url).toBe(
      `https://api.solus.test/api/v1/projects/${PROJECT}/members/me/machines/${COMPANION}`
    )
    expect(init.method).toBe('PUT')
    expect(init.redirect).toBe('error')
    expect(new Headers(init.headers).get('authorization')).toBe('Bearer tok')
    expect(JSON.parse(String(init.body))).toEqual({
      hostname: 'bench-1',
      os: 'linux',
      arch: 'arm64'
    })
  })

  it('does nothing until token, project and identity are all present', async () => {
    const h = harness({ identity: null })
    const reporter = startMachineReporter(h.deps)
    reporter.setProject(PROJECT)
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(0)
    reporter.setToken('tok')
    await settle()
    expect(h.calls).toHaveLength(0)
    h.identity = { id: COMPANION, name: 'bench-1' }
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(1)
  })

  it('an unchanged payload is never re-sent; a changed hostname is, after the debounce', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    reporter.onCompanionUp()
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(1)
    h.platform = { ...h.platform, hostname: 'bench-2' }
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(1)
    expect(h.timers.filter((t) => !t.cancelled).map((t) => t.ms)).toEqual([
      MACHINE_REPORT_DEBOUNCE_MS
    ])
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS
    fireTimers(h)
    await settle()
    expect(h.calls).toHaveLength(2)
    expect(JSON.parse(String(h.calls[1].init.body)).hostname).toBe('bench-2')
  })

  it('a companion respawn after the window sends one PUT only when the payload changed', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS + 1
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(1)
    h.identity = { id: 'b'.repeat(32), name: 'bench-1' }
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(2)
    expect(h.calls[1].url).toContain(`/machines/${'b'.repeat(32)}`)
  })
})

describe('failure, sign-out and guards', () => {
  it('a failed send is retried on the next trigger, not on a timer', async () => {
    const h = harness()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const reporter = startMachineReporter(h.deps)
    h.respond.ok = false
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(1)
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('[machine-report]'),
      expect.anything()
    )
    expect(h.timers.filter((t) => !t.cancelled)).toHaveLength(0)
    h.respond.ok = true
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS + 1
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(2)
    warn.mockRestore()
  })

  it('token null stops everything: pending timers cancelled, no further sends', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    h.platform = { ...h.platform, hostname: 'bench-2' }
    reporter.onCompanionUp()
    expect(h.timers.filter((t) => !t.cancelled)).toHaveLength(1)
    reporter.setToken(null)
    expect(h.timers.filter((t) => !t.cancelled)).toHaveLength(0)
    reporter.onCompanionUp()
    reporter.sendPreferences({ electrical: 'XT30' })
    await settle()
    expect(h.calls).toHaveLength(1)
  })

  it('refuses a non-https base, a malformed project id and a malformed token', async () => {
    const h = harness()
    h.deps.apiBaseUrl = 'http://api.solus.test/api/v1'
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(0)
    const local = harness()
    local.deps.apiBaseUrl = 'http://127.0.0.1:8000/api/v1'
    const r2 = startMachineReporter(local.deps)
    r2.setToken('tok\r\nX-Injected: 1')
    r2.setProject(PROJECT)
    await settle()
    expect(local.calls).toHaveLength(0)
    r2.setProject('../../admin')
    r2.setToken('tok')
    await settle()
    expect(local.calls).toHaveLength(0)
    r2.setProject(PROJECT)
    await settle()
    expect(local.calls).toHaveLength(1)
    expect(local.calls[0].url.startsWith('http://127.0.0.1:8000/api/v1/projects/')).toBe(true)
  })

  it('an identity that throws is logged and never escapes a trigger or the timer', async () => {
    const h = harness()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(1)
    h.platform = { ...h.platform, hostname: 'bench-2' }
    reporter.onCompanionUp()
    expect(h.timers.filter((t) => !t.cancelled)).toHaveLength(1)
    h.deps.identity = () => {
      throw new Error('EROFS')
    }
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS
    expect(() => fireTimers(h)).not.toThrow()
    expect(() => reporter.onCompanionUp()).not.toThrow()
    expect(() => reporter.setProject('3b1f2a3c-4d5e-4f60-8a71-9b8c7d6e5f41')).not.toThrow()
    await settle()
    expect(h.calls).toHaveLength(1)
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('[machine-report]'), 'EROFS')
    warn.mockRestore()
  })

  it('sign-out forgets the saved preferences: the next member gets no mirror until they save', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    reporter.sendPreferences({ electrical: 'XT30' })
    await settle()
    expect(h.calls).toHaveLength(2)
    reporter.setToken(null)
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS + 1
    reporter.setToken('tok-other')
    await settle()
    expect(h.calls.map((c) => c.url.split('/members/me/')[1])).toEqual([
      `machines/${COMPANION}`,
      'preferences',
      `machines/${COMPANION}`
    ])
  })

  it('a token relayed straight from one account to another forgets the saved preferences too', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok-a')
    reporter.setProject(PROJECT)
    reporter.sendPreferences({ electrical: 'XT30' })
    await settle()
    expect(h.calls).toHaveLength(2)
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS + 1
    reporter.setToken('tok-b')
    await settle()
    // Account B gets the machine report (same machine) but never A's saved preferences.
    expect(h.calls.map((c) => c.url.split('/members/me/')[1])).toEqual([
      `machines/${COMPANION}`,
      'preferences',
      `machines/${COMPANION}`
    ])
    expect(h.calls[2].init.headers).toMatchObject({ Authorization: 'Bearer tok-b' })
  })
})

describe('preferences lane and stop', () => {
  it('sendPreferences PUTs the shared subset, debounced per payload hash', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.sendPreferences({ electrical: 'XT30' })
    await settle()
    expect(h.calls).toHaveLength(0)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls.map((c) => c.url.split('/members/me/')[1])).toEqual([
      `machines/${COMPANION}`,
      'preferences'
    ])
    expect(JSON.parse(String(h.calls[1].init.body))).toEqual({
      schema_version: 1,
      shared: { electrical: 'XT30' }
    })
    reporter.sendPreferences({ electrical: 'XT30' })
    await settle()
    expect(h.calls).toHaveLength(2)
    reporter.sendPreferences({ electrical: 'XT30', mechanical: 'M3' })
    await settle()
    expect(h.calls).toHaveLength(2)
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS
    fireTimers(h)
    await settle()
    expect(h.calls).toHaveLength(3)
    expect(JSON.parse(String(h.calls[2].init.body)).shared).toEqual({
      electrical: 'XT30',
      mechanical: 'M3'
    })
  })

  it('an empty shared subset is sent only after an explicit save, never on project open', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    expect(h.calls).toHaveLength(1)
    h.clock.now += MACHINE_REPORT_DEBOUNCE_MS + 1
    reporter.sendPreferences({})
    await settle()
    expect(h.calls).toHaveLength(2)
    expect(JSON.parse(String(h.calls[1].init.body))).toEqual({ schema_version: 1, shared: {} })
  })

  it('stop cancels pending timers and ignores later triggers', async () => {
    const h = harness()
    const reporter = startMachineReporter(h.deps)
    reporter.setToken('tok')
    reporter.setProject(PROJECT)
    await settle()
    h.platform = { ...h.platform, hostname: 'bench-2' }
    reporter.onCompanionUp()
    reporter.stop()
    expect(h.timers.filter((t) => !t.cancelled)).toHaveLength(0)
    reporter.onCompanionUp()
    await settle()
    expect(h.calls).toHaveLength(1)
  })
})
