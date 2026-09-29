// SOLUSDEV-311: `window.solus.diagnostics` — a thin invoke wrapper that
// re-validates what main answers (the preload trusts nothing it relays) and
// never rejects: reporting an error must not itself throw in the renderer.
import { describe, it, expect } from 'vitest'
import { createDiagnosticsBridge } from './diagnosticsBridge'
import { DIAG_CHANNELS, type RendererErrorReport } from '../main/diagnostics/diagnostics.constants'

const REPORT: RendererErrorReport = {
  origin: 'render',
  surface: 'bench',
  name: 'TypeError',
  message: 'boom'
}
const ACK = { fingerprint: '0123456789abcdef', first: true, appVersion: '1.0.0' }
const CRASH = {
  origin: 'main_process',
  surface: 'main',
  errorName: 'TypeError',
  fingerprint: '0123456789abcdef',
  appVersion: '1.0.0'
}

const bridgeAnswering = (
  answer: unknown,
  calls: unknown[][] = []
): ReturnType<typeof createDiagnosticsBridge> =>
  createDiagnosticsBridge({
    invoke: async (...args: unknown[]) => {
      calls.push(args)
      if (answer instanceof Error) throw answer
      return answer
    }
  })

describe('createDiagnosticsBridge', () => {
  it('sends a report on the report channel and returns a valid ack', async () => {
    const calls: unknown[][] = []
    expect(await bridgeAnswering(ACK, calls).report(REPORT)).toEqual(ACK)
    expect(calls[0]).toEqual([DIAG_CHANNELS.report, REPORT])
  })

  it.each([
    ['null', null],
    ['a malformed ack', { fingerprint: 'nope', first: 'yes' }]
  ])('answers null for %s', async (_label, answer) => {
    expect(await bridgeAnswering(answer).report(REPORT)).toBeNull()
  })

  it('answers null (never rejects) when the invoke fails', async () => {
    await expect(bridgeAnswering(new Error('no handler')).report(REPORT)).resolves.toBeNull()
  })

  it('sends consent on its channel and answers whether main took it', async () => {
    const calls: unknown[][] = []
    expect(await bridgeAnswering(true, calls).setConsent(true)).toBe(true)
    expect(calls[0]).toEqual([DIAG_CHANNELS.setConsent, true])
    expect(await bridgeAnswering('yes').setConsent(false)).toBe(false)
    expect(await bridgeAnswering(new Error('x')).setConsent(true)).toBe(false)
  })

  it('takes the crash marker and validates it', async () => {
    const calls: unknown[][] = []
    expect(await bridgeAnswering(CRASH, calls).takeCrashMarker()).toEqual(CRASH)
    expect(calls[0]).toEqual([DIAG_CHANNELS.takeCrashMarker])
    expect(await bridgeAnswering({ ...CRASH, origin: 'render' }).takeCrashMarker()).toBeNull()
  })
})
