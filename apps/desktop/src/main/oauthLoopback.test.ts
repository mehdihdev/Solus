import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createServer } from 'node:net'

// Mock Electron so the module imports under the test runner and we can assert
// the system browser is (or isn't) opened. `vi.hoisted` lets the factory (which
// is hoisted above imports) reference the spy safely.
const { openExternal } = vi.hoisted(() => ({ openExternal: vi.fn() }))
vi.mock('electron', () => ({ shell: { openExternal } }))

// The module under test is re-imported per test (see beforeEach) because it
// keeps FLOW STATE in a module-global (`active`). Static bindings would share
// that state across tests, and one abandoned flow would poison every test after
// it — which is exactly how three of these failed at once in CI.
let oauth: typeof import('./oauthLoopback')

const AUTHORIZE = 'https://abc.supabase.co/auth/v1/authorize?provider=github'

// An EPHEMERAL port per test file. The real flow uses the fixed 53682 that the
// providers' redirect URLs are registered against, but binding it here makes the
// suite fight a running dev app that is mid-sign-in — which is exactly how these
// tests failed once. The port constant itself is asserted in oauthCallback.test.ts.
let PORT = 0
const base = (): string => `http://127.0.0.1:${PORT}/auth/callback`

// The retry budget and the test timeout are derived from ONE pair of numbers on
// purpose. They used to be set independently: the helper below retried for 10s
// while vitest's unconfigured default killed the test at 5s, so the helper was
// allowed to run twice as long as the test was allowed to live. On a fast
// machine the first attempt succeeds and it never shows; on the 2-vCPU/1GiB CI
// runner (291s for a suite that takes 22s here) it is fatal, and it took out
// three tests at once via the shared-state cascade below.
const RETRY_TRIES = 500
const RETRY_SLEEP_MS = 20
const CALLBACK_BUDGET_MS = RETRY_TRIES * RETRY_SLEEP_MS
/** Any test that binds a socket must be allowed to outlive the helper it awaits. */
const SOCKET_TEST_TIMEOUT_MS = CALLBACK_BUDGET_MS + 10_000

/** Hit the loopback callback, retrying until the server is listening.
 *
 *  The loop exits on the first success, so a generous cap costs nothing on a
 *  healthy run and only widens the margin on a loaded machine — 2s was tight
 *  enough to fail here while a dev server and the app were also running.
 *
 *  `Connection: close` is load-bearing, not tidiness. `fetch` (undici) keeps the
 *  socket alive by default, and the flow resolves only once every listening
 *  socket is fully released — so `server.close()` sat waiting on that idle
 *  connection and EVERY test in this file took a flat ~3.0s. Three of the five
 *  seconds vitest allowed were spent waiting for a socket nobody was using,
 *  which is what left CI with no headroom. Closing the connection took the file
 *  from 21s to 0.6s. */
async function hitCallback(url: string): Promise<number> {
  for (let i = 0; i < RETRY_TRIES; i++) {
    try {
      const res = await fetch(url, { headers: { connection: 'close' } })
      return res.status
    } catch {
      await new Promise((r) => setTimeout(r, RETRY_SLEEP_MS))
    }
  }
  throw new Error('loopback server never came up')
}

/** Whether this machine can bind ::1 at all. Containers frequently ship without
 *  IPv6, and the module treats that as a non-failure by design ("a machine with
 *  IPv6 disabled simply has no ::1 to bind"), so the IPv6 assertion below is
 *  skipped rather than failed where the stack does not exist. */
async function hasIpv6Loopback(): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = createServer()
    probe.once('error', () => resolve(false))
    probe.listen(0, '::1', () => probe.close(() => resolve(true)))
  })
}
const IPV6_AVAILABLE = await hasIpv6Loopback()

beforeEach(async () => {
  openExternal.mockClear()
  // A FRESH module per test. `oauthLoopback` keeps its in-flight flow in a
  // module-global `active`. That used to be guarded by a flat refusal held for
  // TIMEOUT_MS — five minutes — so a test that timed out before its callback
  // landed left the flow armed and every later test got that error instead of a
  // listening server, turning one environmental hiccup into three CI failures.
  // A new flow now supersedes an abandoned one, which cures the cascade; the
  // reset stays because per-test isolation is worth having on its own.
  vi.resetModules()
  oauth = await import('./oauthLoopback')
  // Step the port per test so a socket lingering in TIME_WAIT cannot bleed into
  // the next one.
  //
  // BELOW the kernel's ephemeral range (/proc/sys/net/ipv4/ip_local_port_range,
  // 32768-60999 by default) on purpose. This used to pick 49500-53499, which is
  // inside it, so the bind raced every OUTBOUND connection on the machine — a
  // dev server, the Electron app, a parallel test run. That surfaced as the
  // useless "loopback server never came up" (the EADDRINUSE is swallowed by the
  // retry loop), roughly once per 25 runs. Keep this range unassignable.
  PORT = 20000 + Math.floor(Math.random() * 9000)
})

describe('awaitGithubCallback', () => {
  registerOAuthSuccessAndUrlValidationTests()
  registerOAuthSupersessionAndTimeoutTests()
  registerOAuthDualStackAndStateTests()
})

// The cancel seam (SOLUSDEV-165): closing the connect wizard mid-handshake must
// resolve the parked flow NOW — not leave the loopback armed for five minutes
// capturing a code the user no longer wants handled.
describe('cancelActiveOAuth', () => {
  it(
    'resolves the in-flight flow with a cancelled error and frees the port for a retry',
    async () => {
      const pending = oauth.awaitOAuthCallback(AUTHORIZE, 'cx-state', PORT)
      // Wait until the server listens (a wrong-state probe 404s once it is up).
      await hitCallback(`${base()}?state=wrong`)

      expect(oauth.cancelActiveOAuth()).toBe(true)
      expect(await pending).toEqual({ error: 'Sign-in was cancelled.' })

      // The sockets are released: a fresh flow on the SAME port succeeds.
      const again = oauth.awaitOAuthCallback(AUTHORIZE, 'cy-state', PORT)
      const status = await hitCallback(`${base()}?state=cy-state&code=c2`)
      expect(status).toBe(200)
      expect(await again).toEqual({ code: 'c2' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  it('reports false when nothing is in flight', () => {
    expect(oauth.cancelActiveOAuth()).toBe(false)
  })
})

// The defect that turned ONE environmental hiccup into THREE CI failures.
//
// `oauthLoopback` used to REFUSE a second flow while one was in flight and hold
// that for five minutes, so a test that timed out before its callback arrived
// left the flow armed and every later test in the file got "A sign-in is already
// in progress." instead of a listening server. Three tests died that way while
// the first one's real cause scrolled past.
//
// Supersede kills that cascade at the source — an abandoned flow can no longer
// poison the next caller, in tests or in the app. The per-test module reset
// stays as belt and braces, and these two pin both halves.
describe('test isolation', () => {
  it(
    'an abandoned flow no longer poisons the next one (the cascade, cured)',
    async () => {
      const abandoned = oauth.awaitOAuthCallback(AUTHORIZE, 'abandoned', PORT)
      // Let the first flow claim `active` without ever satisfying it.
      await hitCallback(`${base()}?state=nope`).catch(() => undefined)

      const second = oauth.awaitOAuthCallback(AUTHORIZE, 'next', PORT)

      expect(await abandoned).toEqual({ error: 'Sign-in was cancelled.' })
      await hitCallback(`${base()}?state=next&code=ok`)
      expect(await second).toEqual({ code: 'ok' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  it(
    'and a fresh module instance accepts a flow again',
    async () => {
      // `beforeEach` re-imported the module, so the previous test's abandoned flow
      // cannot reach this one. Without that reset this call returns the error
      // above and the assertion below fails — which is the regression.
      vi.resetModules()
      const fresh = await import('./oauthLoopback')

      const pending = fresh.awaitOAuthCallback(AUTHORIZE, 'fresh-state', PORT)
      const status = await hitCallback(`${base()}?state=fresh-state&code=fresh-code`)

      expect(status).toBe(200)
      expect(await pending).toEqual({ code: 'fresh-code' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )
})

function registerOAuthSuccessAndUrlValidationTests(): void {
  it(
    'opens the https authorize URL and resolves with the code on a matching callback',
    async () => {
      const redirect = oauth.getRedirectUrl()
      expect(redirect).toContain('127.0.0.1:53682/auth/callback?solus_cb=')
      const state = new URL(redirect).searchParams.get('solus_cb')

      const pending = oauth.awaitGithubCallback(AUTHORIZE, PORT)
      const status = await hitCallback(`${base()}?solus_cb=${state}&code=auth-code-1`)

      expect(status).toBe(200)
      expect(await pending).toEqual({ code: 'auth-code-1' })
      expect(openExternal).toHaveBeenCalledWith(AUTHORIZE)
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  it(
    'ignores a forged callback with the wrong state, then accepts the real one',
    async () => {
      const redirect = oauth.getRedirectUrl()
      const state = new URL(redirect).searchParams.get('solus_cb')
      const pending = oauth.awaitGithubCallback(AUTHORIZE, PORT)

      const forged = await hitCallback(`${base()}?solus_cb=wrong&code=evil`)
      expect(forged).toBe(404)

      await hitCallback(`${base()}?solus_cb=${state}&code=real-code`)
      expect(await pending).toEqual({ code: 'real-code' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  it('refuses a non-https authorize URL and never opens the browser', async () => {
    oauth.getRedirectUrl()
    const result = await oauth.awaitGithubCallback('file:///etc/passwd', PORT)
    expect(result).toEqual({ error: 'Invalid sign-in URL.' })
    expect(openExternal).not.toHaveBeenCalled()
  })
}

function registerOAuthSupersessionAndTimeoutTests(): void {
  it(
    'supersedes an in-flight sign-in instead of refusing the new one',
    async () => {
      // Nothing tells us the user closed the browser tab, so an abandoned flow
      // used to hold the port for five minutes and answer "A sign-in is already
      // in progress." to every retry. Refusing is only right if the earlier flow
      // might still complete; a person clicking sign-in again is saying it will
      // not. The old flow settles as cancelled — never left dangling.
      oauth.getRedirectUrl()
      const abandoned = oauth.awaitGithubCallback(AUTHORIZE, PORT)
      await hitCallback(`${base()}?solus_cb=ping`).catch(() => undefined)

      const redirect = oauth.getRedirectUrl()
      const state = new URL(redirect).searchParams.get('solus_cb')
      const second = oauth.awaitGithubCallback(AUTHORIZE, PORT)

      expect(await abandoned).toEqual({ error: 'Sign-in was cancelled.' })

      // And the port really did change hands: the new flow is listening.
      await hitCallback(`${base()}?solus_cb=${state}&code=done`)
      expect(await second).toEqual({ code: 'done' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  // Connector OAuth: the redirect URI must stay constant for strict providers
  // (Onshape), so the nonce is the provider's echoed `state`, not solus_cb.
  it(
    'captures a connector callback matched on the provider state',
    async () => {
      expect(oauth.getConnectorRedirectUrl()).toBe('http://localhost:53682/auth/callback')

      const pending = oauth.awaitOAuthCallback(AUTHORIZE, 'backend-state-abc', PORT)
      const forged = await hitCallback(`${base()}?state=wrong&code=evil`)
      expect(forged).toBe(404)

      const status = await hitCallback(`${base()}?state=backend-state-abc&code=real-code`)
      expect(status).toBe(200)
      expect(await pending).toEqual({ code: 'real-code' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  // The reason both loopback stacks are bound: the connector redirect says
  // `localhost`, which resolves to ::1 first on many systems. A callback arriving
  // over IPv6 must land, or the sign-in hangs until it times out.
  it.skipIf(!IPV6_AVAILABLE)(
    'accepts a connector callback over IPv6 loopback',
    async () => {
      const pending = oauth.awaitOAuthCallback(AUTHORIZE, 'v6-state', PORT)

      const status = await hitCallback(
        `http://[::1]:${PORT}/auth/callback?state=v6-state&code=v6-code`
      )

      expect(status).toBe(200)
      expect(await pending).toEqual({ code: 'v6-code' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )
}

function registerOAuthDualStackAndStateTests(): void {
  it(
    'accepts the same connector callback over IPv4 loopback',
    async () => {
      const pending = oauth.awaitOAuthCallback(AUTHORIZE, 'v4-state', PORT)

      const status = await hitCallback(`${base()}?state=v4-state&code=v4-code`)

      expect(status).toBe(200)
      expect(await pending).toEqual({ code: 'v4-code' })
    },
    SOCKET_TEST_TIMEOUT_MS
  )

  it(
    'never logs the auth code',
    async () => {
      const spies = [
        vi.spyOn(console, 'log').mockImplementation(() => {}),
        vi.spyOn(console, 'error').mockImplementation(() => {}),
        vi.spyOn(console, 'warn').mockImplementation(() => {})
      ]
      const redirect = oauth.getRedirectUrl()
      const state = new URL(redirect).searchParams.get('solus_cb')
      const pending = oauth.awaitGithubCallback(AUTHORIZE, PORT)
      await hitCallback(`${base()}?solus_cb=${state}&code=secret-code-xyz`)
      await pending
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(JSON.stringify(call)).not.toContain('secret-code-xyz')
        }
        spy.mockRestore()
      }
    },
    SOCKET_TEST_TIMEOUT_MS
  )
}
