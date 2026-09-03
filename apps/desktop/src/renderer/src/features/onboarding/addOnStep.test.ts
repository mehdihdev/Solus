// "One connect, FeatureScript comes with it" (SOLUSDEV-168).
//
// The add-on used to be a separate button on an already-connected source. It is
// now part of the connect — and the property that matters most is the one these
// tests spend the most effort on: it can never cost you the connection.
import { describe, expect, it, vi } from 'vitest'
import type { IntegrationHosted } from '../../lib/api/resources'
import { addOnStep, type AddOnApi, type AddOnStepDeps } from './addOnStep'

const HOSTED: IntegrationHosted = {
  server: 'onshape_fs',
  display_name: 'FeatureScript',
  notice: 'It runs as you.',
  subscribe_url: 'https://cad.onshape.com/appstore/apps/x'
}

const CTX = { projectId: 'p1', sourceId: 's1' }

function deps(over: Partial<AddOnStepDeps> = {}): AddOnStepDeps {
  const api: AddOnApi = {
    startHostedOAuth: vi.fn().mockResolvedValue({ authorize_url: 'https://x/a', state: 'st' }),
    exchangeHostedOAuth: vi.fn().mockResolvedValue({ state: 'ready' })
  }
  return {
    hosted: HOSTED,
    bridge: {
      getRedirectUrl: vi.fn(),
      awaitGithub: vi.fn(),
      getConnectorRedirectUrl: vi.fn(),
      awaitOAuth: vi.fn().mockResolvedValue({ code: 'auth-code' })
    },
    api,
    onProgress: vi.fn(),
    isCancelled: () => false,
    ...over
  }
}

describe('enabling the add-on during the connect', () => {
  it('runs the second handshake and reports it enabled', async () => {
    const d = deps()
    const note = await addOnStep(d)(CTX)

    expect(d.api.startHostedOAuth).toHaveBeenCalledWith('p1', 's1', 'onshape_fs')
    expect(d.bridge?.awaitOAuth).toHaveBeenCalledWith('https://x/a', 'st')
    expect(d.api.exchangeHostedOAuth).toHaveBeenCalledWith('p1', 's1', 'onshape_fs', {
      state: 'st',
      code: 'auth-code'
    })
    expect(note).toBe('FeatureScript enabled')
  })

  it('tells the user what is happening while it happens', async () => {
    const onProgress = vi.fn()
    await addOnStep(deps({ onProgress }))(CTX)
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ phase: 'busy', stage: 'link', label: 'Enabling FeatureScript…' })
    )
  })

  it('does nothing for a connector that carries no add-on', async () => {
    const d = deps({ hosted: null })
    expect(await addOnStep(d)(CTX)).toBeNull()
    expect(d.api.startHostedOAuth).not.toHaveBeenCalled()
    expect(d.onProgress).not.toHaveBeenCalled()
  })
})

describe('it can never cost you the connection', () => {
  it('survives the backend refusing to start it', async () => {
    const d = deps()
    vi.mocked(d.api.startHostedOAuth).mockRejectedValue(new Error('boom'))
    expect(await addOnStep(d)(CTX)).toBeNull()
  })

  it('survives the sign-in failing or being closed', async () => {
    for (const callback of [{ error: 'Sign-in was cancelled.' }, {}]) {
      const d = deps()
      vi.mocked(d.bridge!.awaitOAuth).mockResolvedValue(callback)
      expect(await addOnStep(d)(CTX)).toBeNull()
      expect(d.api.exchangeHostedOAuth).not.toHaveBeenCalled()
    }
  })

  it('survives the exchange failing', async () => {
    const d = deps()
    vi.mocked(d.api.exchangeHostedOAuth).mockRejectedValue(new Error('nope'))
    expect(await addOnStep(d)(CTX)).toBeNull()
  })

  it('reports no note when the account is not subscribed', async () => {
    // Not an error — the vendor simply has not sold them the app. The Sources
    // page carries the deep link and the re-check from here.
    const d = deps()
    vi.mocked(d.api.exchangeHostedOAuth).mockResolvedValue({ state: 'subscription_required' })
    expect(await addOnStep(d)(CTX)).toBeNull()
  })
})

describe('a closed wizard stops it', () => {
  it('never opens a browser for a flow nobody is watching', async () => {
    const d = deps({ isCancelled: () => true })
    expect(await addOnStep(d)(CTX)).toBeNull()
    expect(d.api.startHostedOAuth).not.toHaveBeenCalled()
    expect(d.bridge?.awaitOAuth).not.toHaveBeenCalled()
  })

  it('stops after the handshake if the wizard closed meanwhile', async () => {
    let cancelled = false
    const d = deps({ isCancelled: () => cancelled })
    vi.mocked(d.bridge!.awaitOAuth).mockImplementation(async () => {
      cancelled = true
      return { code: 'auth-code' }
    })
    expect(await addOnStep(d)(CTX)).toBeNull()
    expect(d.api.exchangeHostedOAuth).not.toHaveBeenCalled()
  })
})
