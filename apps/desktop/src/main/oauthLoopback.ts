// Loopback OAuth capture for the main process. Opens the provider authorize URL
// in the user's system browser and runs a short-lived localhost server to catch
// the redirect, returning the PKCE code to the caller (the renderer, via IPC).
//
// Hardening: server binds to 127.0.0.1 only; one flow at a time; a per-flow CSRF
// `state` nonce that the callback must echo; only https authorize URLs are opened;
// a timeout so it never lingers. The code/token are never logged.
import { createServer, type Server } from 'node:http'
import { randomUUID } from 'node:crypto'
import { shell } from 'electron'
import {
  OAUTH_LOOPBACK_PORT,
  OAUTH_LOOPBACK_HOST,
  loopbackRedirectUrl,
  isValidAuthorizeUrl,
  parseOAuthCallback,
  type OAuthCallbackResult
} from './oauthCallback'

const TIMEOUT_MS = 5 * 60 * 1000

const DONE_HTML = `<!doctype html><html><head><meta charset="utf-8"><title>Solus</title></head>
<body style="font-family:system-ui;background:#0A0C0F;color:#E6E9EE;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><h2 style="font-weight:600">You're signed in</h2>
<p style="color:#828B99">Return to Solus — you can close this tab.</p></div></body></html>`

let active: Server | null = null
let currentState = ''

/** Issue a fresh CSRF state and return the loopback redirect URL carrying it. */
export function getRedirectUrl(): string {
  currentState = randomUUID()
  return loopbackRedirectUrl(currentState)
}

/**
 * Open `authorizeUrl` in the system browser and resolve once the provider
 * redirects back to the loopback server with our state. Resolves `{ code }` or
 * `{ error }`. `getRedirectUrl()` must have been called first (same flow).
 */
export function awaitGithubCallback(authorizeUrl: string): Promise<OAuthCallbackResult> {
  if (active) return Promise.resolve({ error: 'A sign-in is already in progress.' })
  if (!isValidAuthorizeUrl(authorizeUrl)) {
    return Promise.resolve({ error: 'Invalid sign-in URL.' })
  }
  if (!currentState) return Promise.resolve({ error: 'Sign-in was not initialized.' })

  const expectedState = currentState
  return new Promise<OAuthCallbackResult>((resolve) => {
    let settled = false
    const finish = (result: OAuthCallbackResult): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      const srv = active
      active = null
      // Resolve only once the listening socket is fully released, so the fixed
      // port is free for the next attempt.
      if (srv) srv.close(() => resolve(result))
      else resolve(result)
    }

    const server = createServer((req, res) => {
      const parsed = req.url ? parseOAuthCallback(req.url, expectedState) : null
      if (parsed === null) {
        res.statusCode = 404
        res.end()
        return
      }
      res.statusCode = 200
      res.setHeader('Content-Type', 'text/html; charset=utf-8')
      res.end(DONE_HTML)
      finish(parsed)
    })

    server.on('error', (err: NodeJS.ErrnoException) => {
      const msg =
        err.code === 'EADDRINUSE'
          ? `Port ${OAUTH_LOOPBACK_PORT} is in use — close the other process and retry.`
          : 'Could not start the local sign-in listener.'
      active = null
      finish({ error: msg })
    })

    const timer = setTimeout(() => finish({ error: 'Sign-in timed out.' }), TIMEOUT_MS)

    active = server
    server.listen(OAUTH_LOOPBACK_PORT, OAUTH_LOOPBACK_HOST, () => {
      void shell.openExternal(authorizeUrl)
    })
  })
}
