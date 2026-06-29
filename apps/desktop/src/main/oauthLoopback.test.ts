import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock Electron so the module imports under the test runner and we can assert
// the system browser is (or isn't) opened. `vi.hoisted` lets the factory (which
// is hoisted above imports) reference the spy safely.
const { openExternal } = vi.hoisted(() => ({ openExternal: vi.fn() }))
vi.mock('electron', () => ({ shell: { openExternal } }))

import { getRedirectUrl, awaitGithubCallback } from './oauthLoopback'

const AUTHORIZE = 'https://abc.supabase.co/auth/v1/authorize?provider=github'

/** Hit the loopback callback, retrying until the server is listening. */
async function hitCallback(url: string): Promise<number> {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(url)
      return res.status
    } catch {
      await new Promise((r) => setTimeout(r, 20))
    }
  }
  throw new Error('loopback server never came up')
}

beforeEach(() => {
  openExternal.mockClear()
})

describe('awaitGithubCallback', () => {
  it('opens the https authorize URL and resolves with the code on a matching callback', async () => {
    const redirect = getRedirectUrl()
    expect(redirect).toContain('127.0.0.1:53682/auth/callback?solus_cb=')

    const pending = awaitGithubCallback(AUTHORIZE)
    const status = await hitCallback(`${redirect}&code=auth-code-1`)

    expect(status).toBe(200)
    expect(await pending).toEqual({ code: 'auth-code-1' })
    expect(openExternal).toHaveBeenCalledWith(AUTHORIZE)
  })

  it('ignores a forged callback with the wrong state, then accepts the real one', async () => {
    const redirect = getRedirectUrl()
    const pending = awaitGithubCallback(AUTHORIZE)

    const forged = await hitCallback(
      'http://127.0.0.1:53682/auth/callback?solus_cb=wrong&code=evil'
    )
    expect(forged).toBe(404)

    await hitCallback(`${redirect}&code=real-code`)
    expect(await pending).toEqual({ code: 'real-code' })
  })

  it('refuses a non-https authorize URL and never opens the browser', async () => {
    getRedirectUrl()
    const result = await awaitGithubCallback('file:///etc/passwd')
    expect(result).toEqual({ error: 'Invalid sign-in URL.' })
    expect(openExternal).not.toHaveBeenCalled()
  })

  it('refuses an overlapping sign-in while one is in flight', async () => {
    const redirect = getRedirectUrl()
    const first = awaitGithubCallback(AUTHORIZE)
    // give the first server a moment to claim the port
    await hitCallback('http://127.0.0.1:53682/auth/callback?solus_cb=ping').catch(() => undefined)

    const second = await awaitGithubCallback(AUTHORIZE)
    expect(second).toEqual({ error: 'A sign-in is already in progress.' })

    await hitCallback(`${redirect}&code=done`)
    await first
  })

  it('never logs the auth code', async () => {
    const spies = [
      vi.spyOn(console, 'log').mockImplementation(() => {}),
      vi.spyOn(console, 'error').mockImplementation(() => {}),
      vi.spyOn(console, 'warn').mockImplementation(() => {})
    ]
    const redirect = getRedirectUrl()
    const pending = awaitGithubCallback(AUTHORIZE)
    await hitCallback(`${redirect}&code=secret-code-xyz`)
    await pending
    for (const spy of spies) {
      for (const call of spy.mock.calls) {
        expect(JSON.stringify(call)).not.toContain('secret-code-xyz')
      }
      spy.mockRestore()
    }
  })
})
