// SOLUSDEV-311 (security review M3, human decision): Sentry sends only for
// users who turned data-collection consent on. Main starts closed; the main
// window tells it the signed-in user's consent, flips it when Settings saves a
// change, and closes it again on sign-out — never re-opened by a late fetch.
import { describe, it, expect, vi } from 'vitest'
import { createConsentSync } from './errorConsent'
import type { DiagnosticsBridge } from '../desktopBridge'

function setup(fetchConsent: () => Promise<boolean> = async () => true): {
  sync: ReturnType<typeof createConsentSync>
  setConsent: ReturnType<typeof vi.fn>
} {
  const setConsent = vi.fn(async () => true)
  const bridge = { setConsent } as unknown as DiagnosticsBridge
  return { sync: createConsentSync({ bridge: () => bridge, fetchConsent }), setConsent }
}

describe('createConsentSync', () => {
  it('on sign-in, sends the user consent read from their settings', async () => {
    const { sync, setConsent } = setup(async () => true)
    await sync.onAuthStatus('authenticated')
    expect(setConsent).toHaveBeenCalledWith(true)
  })

  it('sends false for a user who has not consented', async () => {
    const { sync, setConsent } = setup(async () => false)
    await sync.onAuthStatus('authenticated')
    expect(setConsent).toHaveBeenCalledWith(false)
  })

  it('closes on sign-out and does nothing while auth is still loading', async () => {
    const { sync, setConsent } = setup()
    await sync.onAuthStatus('loading')
    expect(setConsent).not.toHaveBeenCalled()
    await sync.onAuthStatus('unauthenticated')
    expect(setConsent).toHaveBeenCalledWith(false)
  })

  it('a settings fetch that lands after sign-out cannot re-open it', async () => {
    let resolve: (v: boolean) => void = () => undefined
    const { sync, setConsent } = setup(() => new Promise<boolean>((r) => (resolve = r)))
    const signIn = sync.onAuthStatus('authenticated')
    await sync.onAuthStatus('unauthenticated')
    resolve(true)
    await signIn
    expect(setConsent.mock.calls).toEqual([[false]])
  })

  it('stays closed when the settings fetch fails', async () => {
    const { sync, setConsent } = setup(async () => Promise.reject(new Error('offline')))
    await expect(sync.onAuthStatus('authenticated')).resolves.toBeUndefined()
    expect(setConsent).not.toHaveBeenCalledWith(true)
  })

  it('a sign-in fetch landing after a saved Settings change cannot undo it', async () => {
    let resolve: (v: boolean) => void = () => undefined
    const { sync, setConsent } = setup(() => new Promise<boolean>((r) => (resolve = r)))
    const signIn = sync.onAuthStatus('authenticated')
    sync.onConsentChanged(false)
    resolve(true)
    await signIn
    expect(setConsent.mock.calls).toEqual([[false]])
  })

  it('forwards a saved change from Settings', () => {
    const { sync, setConsent } = setup()
    sync.onConsentChanged(false)
    expect(setConsent).toHaveBeenCalledWith(false)
  })

  it('is a no-op outside Electron', async () => {
    const sync = createConsentSync({ bridge: () => null, fetchConsent: async () => true })
    await expect(sync.onAuthStatus('authenticated')).resolves.toBeUndefined()
    expect(() => sync.onConsentChanged(true)).not.toThrow()
  })
})
