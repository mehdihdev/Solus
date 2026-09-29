// SOLUSDEV-311: the reporter — scrub, fingerprint, dedupe, cap, then log and
// (when configured) Sentry. The first sighting of a fingerprint is the only
// one that reaches Sentry or becomes a data event.
import { describe, it, expect, vi } from 'vitest'
import { createDiagnostics } from './diagnostics'
import type { ErrorLogEntry } from './errorLog'
import type { RendererErrorReport } from './diagnostics.constants'

const REPORT: RendererErrorReport = {
  origin: 'render',
  surface: 'bench',
  name: 'TypeError',
  message: 'boom for ada@example.com',
  stack: 'TypeError: boom\n    at BenchScreen (/Users/ada/x.js:1:1)'
}

function setup(
  sessionCap = 50,
  limits: { sentryCap?: number; maxFingerprints?: number } = {}
): {
  diagnostics: ReturnType<typeof createDiagnostics>
  logged: ErrorLogEntry[]
  sentry: { capture: ReturnType<typeof vi.fn>; flush: ReturnType<typeof vi.fn> }
} {
  const logged: ErrorLogEntry[] = []
  const sentry = { capture: vi.fn(), flush: vi.fn(async () => undefined) }
  const diagnostics = createDiagnostics({
    homeDir: '/Users/ada',
    appVersion: '1.0.0',
    log: { write: (e) => logged.push(e) },
    now: () => new Date('2026-09-26T10:00:00Z'),
    sessionCap,
    ...limits
  })
  diagnostics.setSentry(sentry)
  diagnostics.setConsent(true)
  return { diagnostics, logged, sentry }
}

describe('createDiagnostics', () => {
  it('logs a scrubbed entry and acks the first sighting', () => {
    const { diagnostics, logged } = setup()
    const ack = diagnostics.report(REPORT)
    expect(ack).toEqual({
      fingerprint: expect.stringMatching(/^[0-9a-f]{16}$/),
      first: true,
      appVersion: '1.0.0'
    })
    expect(logged).toHaveLength(1)
    expect(logged[0].message).toBe('boom for [email]')
    expect(logged[0].stack).toContain('(~/x.js:1:1)')
    expect(logged[0].at).toBe('2026-09-26T10:00:00.000Z')
  })

  it('sends only the scrubbed report to Sentry, once per fingerprint', () => {
    const { diagnostics, sentry } = setup()
    diagnostics.report(REPORT)
    diagnostics.report(REPORT)
    expect(sentry.capture).toHaveBeenCalledTimes(1)
    const sent = sentry.capture.mock.calls[0][0]
    expect(JSON.stringify(sent)).not.toContain('ada@example.com')
    expect(JSON.stringify(sent)).not.toContain('/Users/ada')
  })

  it('acks a repeat as not-first and logs a one-line repeat count', () => {
    const { diagnostics, logged } = setup()
    diagnostics.report(REPORT)
    const ack = diagnostics.report(REPORT)
    expect(ack.first).toBe(false)
    expect(logged[1]).toMatchObject({ repeat: 2, fingerprint: logged[0].fingerprint })
    expect(logged[1].stack).toBeUndefined()
  })

  it('stops logging past the session cap (a render loop cannot flood the disk)', () => {
    const { diagnostics, logged } = setup(3)
    for (let i = 0; i < 10; i++) diagnostics.report({ ...REPORT, name: `E${i}` })
    expect(logged).toHaveLength(4)
    expect(logged[3].message).toContain('session report cap reached')
  })

  it('scrubs before it truncates: a token straddling the limit never leaks a fragment', () => {
    const { diagnostics, logged } = setup()
    const jwt = [
      'eyJ' + 'hbGciOiJIUzI1NiJ9',
      'eyJ' + 'zdWIiOiIxMjM0NTY3ODkwIn0',
      'sig_abc-123'
    ].join('.')
    diagnostics.report({ ...REPORT, message: `${'x'.repeat(995)} ${jwt}` })
    expect(logged[0].message).not.toContain('eyJ')
    expect(logged[0].message.length).toBeLessThanOrEqual(1_000)
  })
})

describe('createDiagnostics — consent and bounds', () => {
  it('sends nothing to Sentry without data-collection consent (the default)', () => {
    const logged: ErrorLogEntry[] = []
    const sentry = { capture: vi.fn(), flush: vi.fn(async () => undefined) }
    const d = createDiagnostics({
      homeDir: '',
      appVersion: '1.0.0',
      log: { write: (e) => logged.push(e) }
    })
    d.setSentry(sentry)
    d.report(REPORT)
    expect(sentry.capture).not.toHaveBeenCalled()
    expect(logged).toHaveLength(1)
    d.setConsent(true)
    d.report({ ...REPORT, name: 'RangeError' })
    expect(sentry.capture).toHaveBeenCalledTimes(1)
    d.setConsent(false)
    d.report({ ...REPORT, name: 'SyntaxError' })
    expect(sentry.capture).toHaveBeenCalledTimes(1)
  })

  it('caps Sentry sends per session even when every error is new', () => {
    const { diagnostics, sentry } = setup(1_000, { sentryCap: 5 })
    for (let i = 0; i < 20; i++) diagnostics.report({ ...REPORT, name: `E${'x'.repeat(i)}` })
    expect(sentry.capture).toHaveBeenCalledTimes(5)
  })

  it('bounds the fingerprint map: past it, new errors count as repeats (no event, no Sentry)', () => {
    const { diagnostics, sentry } = setup(1_000, { maxFingerprints: 3 })
    const acks = Array.from({ length: 5 }, (_, i) =>
      diagnostics.report({ ...REPORT, name: `N${'y'.repeat(i)}` })
    )
    expect(acks.map((a) => a.first)).toEqual([true, true, true, false, false])
    expect(sentry.capture).toHaveBeenCalledTimes(3)
  })

  it('still logs when Sentry is not configured', () => {
    const logged: ErrorLogEntry[] = []
    const d = createDiagnostics({
      homeDir: '',
      appVersion: '1.0.0',
      log: { write: (e) => logged.push(e) }
    })
    expect(d.report(REPORT).first).toBe(true)
    expect(logged).toHaveLength(1)
  })

  it('flush resolves without Sentry and delegates with it', async () => {
    const { diagnostics, sentry } = setup()
    await diagnostics.flush(100)
    expect(sentry.flush).toHaveBeenCalledWith(100)
  })
})
