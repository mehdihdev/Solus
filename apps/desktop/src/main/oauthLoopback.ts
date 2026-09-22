// Loopback OAuth capture for the main process. Opens the provider authorize URL
// in the user's system browser and runs a short-lived localhost server to catch
// the redirect, returning the PKCE code to the caller (the renderer, via IPC).
//
// Hardening: server binds to 127.0.0.1 only; one flow at a time; a per-flow CSRF
// `state` nonce that the callback must echo; only https authorize URLs are opened;
// a timeout so it never lingers. The code/token are never logged.
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { randomUUID } from 'node:crypto'
import { shell } from 'electron'
import {
  OAUTH_LOOPBACK_PORT,
  OAUTH_LOOPBACK_HOST,
  OAUTH_LOOPBACK_HOST_V6,
  loopbackRedirectUrl,
  connectorRedirectUrl,
  isValidAuthorizeUrl,
  parseOAuthCallback,
  type OAuthCallbackResult,
  type StateParam
} from './oauthCallback'

const TIMEOUT_MS = 5 * 60 * 1000

const DONE_HTML = `<!doctype html><html><head><meta charset="utf-8"><title>Solus</title></head>
<body style="font-family:system-ui;background:#0A0C0F;color:#E6E9EE;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><h2 style="font-weight:600">You're signed in</h2>
<p style="color:#828B99">Return to Solus — you can close this tab.</p></div></body></html>`

let active: Server[] = []
let currentState = ''
/** The in-flight flow's `finish`, so a wizard close can settle it NOW instead
 *  of leaving the loopback armed for TIMEOUT_MS (SOLUSDEV-165 cancel seam). */
let activeFinish: ((result: OAuthCallbackResult) => void) | null = null
/** Resolves once the in-flight flow's sockets are fully released. A supersede
 *  must await this before binding: `finish` empties `active` synchronously but
 *  the listeners close asynchronously, so rebinding the fixed port immediately
 *  would race into EADDRINUSE. */
let activeReleased: Promise<void> | null = null

/** Cancel the in-flight OAuth capture, if any: the parked promise resolves with
 *  a cancelled error and every loopback socket is released. Returns whether a
 *  flow was actually cancelled. */
export function cancelActiveOAuth(): boolean {
  if (!activeFinish) return false
  activeFinish({ error: 'Sign-in was cancelled.' })
  return true
}

/** Issue a fresh CSRF state and return the loopback redirect URL carrying it.
 *  Supabase sign-in flow only. */
export function getRedirectUrl(): string {
  currentState = randomUUID()
  return loopbackRedirectUrl(currentState)
}

/** The constant redirect URL registered in each provider's OAuth app for the
 *  connector flow. No nonce — strict providers match the URI exactly. */
export function getConnectorRedirectUrl(): string {
  return connectorRedirectUrl()
}

/**
 * Open `authorizeUrl` in the system browser and resolve once the provider
 * redirects back to the loopback server with our state. Resolves `{ code }` or
 * `{ error }`. `getRedirectUrl()` must have been called first (same flow).
 */
export function awaitGithubCallback(
  authorizeUrl: string,
  port: number = OAUTH_LOOPBACK_PORT
): Promise<OAuthCallbackResult> {
  if (!currentState) return Promise.resolve({ error: 'Sign-in was not initialized.' })
  return captureCallback(authorizeUrl, currentState, 'solus_cb', port)
}

/**
 * Connector OAuth (GitHub/GitLab/Onshape/…): the backend minted `expectedState`
 * and the provider echoes it back on the callback, so it is the nonce here —
 * server-side, TTL'd, and stronger than the renderer-local uuid sign-in uses.
 */
export function awaitOAuthCallback(
  authorizeUrl: string,
  expectedState: string,
  port: number = OAUTH_LOOPBACK_PORT
): Promise<OAuthCallbackResult> {
  if (!expectedState) return Promise.resolve({ error: 'Sign-in was not initialized.' })
  return captureCallback(authorizeUrl, expectedState, 'state', port)
}

/** `port` is a seam for tests ONLY: the real flow must use the fixed port that
 *  the providers' redirect URLs are registered against, but binding it makes the
 *  suite collide with a running dev app mid-sign-in. Tests pass an ephemeral
 *  port; nothing in production ever overrides the default. */
async function captureCallback(
  authorizeUrl: string,
  expectedState: string,
  stateParam: StateParam,
  port: number
): Promise<OAuthCallbackResult> {
  if (!isValidAuthorizeUrl(authorizeUrl)) {
    return { error: 'Invalid sign-in URL.' }
  }

  // A NEW sign-in SUPERSEDES an in-flight one rather than being refused.
  //
  // We cannot tell that the user closed the browser tab — nothing reports that
  // — so the previous capture stayed armed for the full TIMEOUT_MS and every
  // retry answered "A sign-in is already in progress." for five minutes after
  // the user had visibly given up. Refusing was only ever right if the earlier
  // flow might still complete; a person clicking sign-in again is saying it will
  // not. The superseded flow settles as cancelled, which its caller already
  // handles, so nothing is left dangling and the port has exactly one owner.
  if (active.length > 0) {
    const released = activeReleased
    cancelActiveOAuth()
    if (released) await released
  }

  return new Promise<OAuthCallbackResult>((resolve) => {
    let settled = false
    let releaseDone = (): void => {}
    activeReleased = new Promise<void>((r) => {
      releaseDone = r
    })
    const finish = (result: OAuthCallbackResult): void => {
      if (settled) return
      settled = true
      activeFinish = null
      clearTimeout(timer)
      const servers = active
      active = []
      // Resolve only once every listening socket is fully released, so the fixed
      // port is free for the next attempt.
      let pending = servers.length
      if (pending === 0) {
        releaseDone()
        resolve(result)
        return
      }
      for (const srv of servers) {
        srv.close(() => {
          pending -= 1
          if (pending === 0) {
            releaseDone()
            resolve(result)
          }
        })
      }
    }

    const handle = callbackHandler(expectedState, stateParam, finish)

    const timer = setTimeout(() => finish({ error: 'Sign-in timed out.' }), TIMEOUT_MS)
    activeFinish = finish

    // BOTH loopback stacks. The connector redirect URL says `localhost` (Onshape
    // rejects a bare IP), and `localhost` resolves to ::1 first on many systems —
    // so listening only on 127.0.0.1 would leave that callback refused and the
    // sign-in hanging until it times out. Both sockets are loopback-only.
    listen(port, OAUTH_LOOPBACK_HOST, handle, finish, () => void shell.openExternal(authorizeUrl))
    // Best effort: a machine with IPv6 disabled simply has no ::1 to bind, which
    // is not a failure — the IPv4 socket above still catches the callback.
    listen(port, OAUTH_LOOPBACK_HOST_V6, handle, finish, undefined, true)
  })
}

/** Bind one loopback socket for this flow. `onReady` runs once it is listening;
 *  `optional` suppresses bind failures for a stack the machine may not have. */
function listen(
  port: number,
  host: string,
  handle: (req: IncomingMessage, res: ServerResponse) => void,
  finish: (result: OAuthCallbackResult) => void,
  onReady?: () => void,
  optional = false
): void {
  const server = createServer(handle)
  server.on('error', (err: NodeJS.ErrnoException) => {
    active = active.filter((s) => s !== server)
    if (optional && err.code !== 'EADDRINUSE') return
    finish({
      error:
        err.code === 'EADDRINUSE'
          ? `Port ${port} is in use — close the other process and retry.`
          : 'Could not start the local sign-in listener.'
    })
  })
  active.push(server)
  server.listen(port, host, onReady)
}

function callbackHandler(
  expectedState: string,
  stateParam: StateParam,
  finish: (result: OAuthCallbackResult) => void
): (req: IncomingMessage, res: ServerResponse) => void {
  return (req, res) => {
    const parsed = req.url
      ? parseOAuthCallback(req.url, expectedState, undefined, stateParam)
      : null
    if (parsed === null) {
      res.statusCode = 404
      res.end()
      return
    }
    res.statusCode = 200
    res.setHeader('Content-Type', 'text/html; charset=utf-8')
    res.end(DONE_HTML)
    finish(parsed)
  }
}
