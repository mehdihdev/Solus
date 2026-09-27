// SOLUSDEV-311: `diag:report` admits any Solus app window (main, SOL, overlay,
// extension host — all the same renderer bundle) and refuses everything else
// (the Stripe checkout window, a navigated-away page). `diag:take-crash-marker`
// admits only the main renderer: it is the one that emits the data event.
import { describe, it, expect, vi } from 'vitest'
import { createDiagnosticsIpc, isAppRendererUrl, surfaceForUrl } from './diagnosticsIpc'

const DEV = 'http://localhost:5173'
const PROD = 'file:///Applications/Solus.app/Contents/Resources/app.asar/out/renderer/index.html'

describe('isAppRendererUrl', () => {
  it.each([
    [`${DEV}/#/`, DEV, true],
    [`${DEV}/#/sol-window`, DEV, true],
    [`${PROD}#/overlay`, PROD, true],
    ['https://checkout.stripe.com/c/pay/x', DEV, false],
    ['http://localhost:5174/#/', DEV, false],
    ['http://localhost:5173.evil.com/#/', DEV, false],
    [`${PROD}.evil#/`, PROD, false],
    ['', DEV, false]
  ])('%s against %s → %s', (url, base, expected) => {
    expect(isAppRendererUrl(url, base)).toBe(expected)
  })
})

describe('surfaceForUrl', () => {
  it.each([
    [`${DEV}/#/`, 'root'],
    [`${DEV}/#/sol-window`, 'sol_window'],
    [`${DEV}/#/overlay`, 'overlay'],
    [`${PROD}#/ext-window/bom`, 'ext_window'],
    ['not a url', 'root']
  ])('%s → %s', (url, surface) => {
    expect(surfaceForUrl(url)).toBe(surface)
  })
})

type Event = { sender: string }

function setup(): {
  ipc: ReturnType<typeof createDiagnosticsIpc>
  report: ReturnType<typeof vi.fn>
  take: ReturnType<typeof vi.fn>
  setConsent: ReturnType<typeof vi.fn>
} {
  const report = vi.fn(() => ({
    fingerprint: '0123456789abcdef',
    first: true,
    appVersion: '1.0.0'
  }))
  const take = vi.fn(() => null)
  const setConsent = vi.fn()
  const ipc = createDiagnosticsIpc({
    diagnostics: { report, setConsent },
    marker: { take },
    isAppSender: (e) => ['app', 'main', 'ext'].includes((e as Event).sender),
    isMainSender: (e) => (e as Event).sender === 'main',
    surfaceOf: (e) => ((e as Event).sender === 'ext' ? 'ext_window' : 'root')
  })
  return { ipc, report, take, setConsent }
}

const REPORT = { origin: 'render', surface: 'bench', name: 'TypeError', message: 'boom' }

describe('createDiagnosticsIpc', () => {
  it('reports a valid payload from an app window and returns the ack', () => {
    const { ipc, report } = setup()
    expect(ipc.report({ sender: 'app' }, REPORT)).toMatchObject({ first: true })
    expect(report).toHaveBeenCalledWith(REPORT)
  })

  it('refuses a foreign sender without reporting', () => {
    const { ipc, report } = setup()
    expect(ipc.report({ sender: 'checkout' }, REPORT)).toBeNull()
    expect(report).not.toHaveBeenCalled()
  })

  it('refuses a malformed payload without reporting', () => {
    const { ipc, report } = setup()
    expect(ipc.report({ sender: 'app' }, { ...REPORT, origin: 'main_process' })).toBeNull()
    expect(report).not.toHaveBeenCalled()
  })

  it("a window's own surface wins over the one the renderer claims", () => {
    const { ipc, report } = setup()
    ipc.report({ sender: 'ext' }, { ...REPORT, surface: 'workspace' })
    expect(report).toHaveBeenCalledWith({ ...REPORT, surface: 'ext_window' })
  })

  it('hands the crash marker only to the main renderer', () => {
    const { ipc, take } = setup()
    expect(ipc.takeCrashMarker({ sender: 'app' })).toBeNull()
    expect(take).not.toHaveBeenCalled()
    ipc.takeCrashMarker({ sender: 'main' })
    expect(take).toHaveBeenCalledTimes(1)
  })

  it('takes consent only from the main renderer, and only a boolean', () => {
    const { ipc, setConsent } = setup()
    expect(ipc.setConsent({ sender: 'app' }, true)).toBe(false)
    expect(ipc.setConsent({ sender: 'main' }, 'yes')).toBe(false)
    expect(setConsent).not.toHaveBeenCalled()
    expect(ipc.setConsent({ sender: 'main' }, true)).toBe(true)
    expect(setConsent).toHaveBeenCalledWith(true)
  })
})
