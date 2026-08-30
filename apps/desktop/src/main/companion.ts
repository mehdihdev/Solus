// Companion supervision for the main process (SOLUSDEV-154 / BRG-04): spawn
// the local bridge companion, relay the Supabase access token over stdin as
// newline-delimited JSON, restart it on unexpected exit with jittered
// exponential backoff, reap orphans from a previous app run via a pidfile,
// and tear the whole process tree down on quit. The token is never logged.
//
// Pure decision logic (command resolution, backoff, pidfile, framing) is
// exported for tests; the process plumbing mirrors oauthLoopback's lifecycle
// discipline (single-flight, settle-once, no lingering resources).
import { app } from 'electron'
import { execFile, execFileSync, spawn, type ChildProcess } from 'node:child_process'
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { companionEnv, findIntegrationsRoot } from './companionEnv'
import { projectWorkspace, realLocalStateDeps } from './localState'
import { resolveApiBaseUrl } from '../renderer/src/lib/cspConnect'
import { join } from 'node:path'

export const BACKOFF_BASE_MS = 1_000
export const BACKOFF_CAP_MS = 30_000
export const BACKOFF_RESET_UPTIME_MS = 60_000
const STOP_GRACE_MS = 3_000

export interface CompanionRuntime {
  isPackaged: boolean
  resourcesPath: string
  platform: NodeJS.Platform
  env: Record<string, string | undefined>
}

/** Where the companion lives: the packaged PyInstaller binary under
 *  `<resources>/companion/`, or the SOLUS_COMPANION_DEV_CMD command line in
 *  dev. Null ⇒ companion disabled for this run. */
export function resolveCompanionCommand(
  rt: CompanionRuntime
): { command: string; args: string[] } | null {
  if (rt.isPackaged) {
    const bin = rt.platform === 'win32' ? 'solus-companion.exe' : 'solus-companion'
    return { command: join(rt.resourcesPath, 'companion', bin), args: [] }
  }
  const devCmd = rt.env.SOLUS_COMPANION_DEV_CMD?.trim()
  if (!devCmd) return null
  const [command, ...args] = devCmd.split(/\s+/)
  return { command, args }
}

/** Equal-jitter exponential backoff: uniform in [step/2, step], step doubling
 *  from 1 s and capped at 30 s. */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const step = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** attempt)
  return Math.round(step / 2 + (step / 2) * random())
}

/** Attempt index for the next restart delay. Starts at -1 (no restarts yet);
 *  a stable run (≥ 60 s uptime) resets the schedule to the 1 s step. */
export function nextRestartAttempt(prevAttempt: number, uptimeMs: number): number {
  return uptimeMs >= BACKOFF_RESET_UPTIME_MS ? 0 : prevAttempt + 1
}

/** Parse a pidfile body into a positive integer pid, or null. */
export function parsePidfile(content: string): number | null {
  const trimmed = content.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const pid = Number(trimmed)
  return pid > 0 ? pid : null
}

/** Whether a pidfile pid from a previous run should be reaped before takeover. */
export function shouldReapPid(filePid: number | null, isAlive: (pid: number) => boolean): boolean {
  return filePid !== null && isAlive(filePid)
}

/** Pid-recycling guard: a pidfile pid is only killed when its command line
 *  identifies it as the companion — the packaged binary (`solus-companion`) or
 *  the dev module run (`python -m solus_companion`). Works on the raw
 *  NUL-separated /proc form and the `ps` form alike. */
export function isCompanionCmdline(cmdline: string): boolean {
  return cmdline.includes('solus-companion') || cmdline.includes('solus_companion')
}

/** One newline-delimited JSON stdin frame: token, or signout when null. */
export function tokenLine(token: string | null): string {
  return token === null
    ? `${JSON.stringify({ type: 'signout' })}\n`
    : `${JSON.stringify({ type: 'token', access_token: token })}\n`
}

/** One newline-delimited JSON stdin frame carrying BYO-license credentials
 *  (SOLUSDEV-102 / MCP-05). Values are never logged and never touch disk. */
export function credentialLine(server: string, secrets: Record<string, string>): string {
  return `${JSON.stringify({ type: 'credential', server, secrets })}\n`
}

/** Upper bound on one credential relay line before framing (M4). The
 *  companion drops any stdin control line over its 16 KiB cap; rejecting an
 *  oversize payload here keeps it off stdin entirely. Sized to the same
 *  16 KiB budget the companion's MAX_CONTROL_FRAME_BYTES enforces. */
export const MAX_CREDENTIAL_SECRETS_BYTES = 16 * 1024

/** True when *secrets* is a flat, non-empty object of non-empty string keys
 *  to string values. Narrows to a record for the caller. */
function isFlatStringRecord(secrets: unknown): secrets is Record<string, string> {
  if (typeof secrets !== 'object' || secrets === null || Array.isArray(secrets)) return false
  const entries = Object.entries(secrets)
  if (entries.length === 0) return false
  return entries.every(([key, value]) => key.length > 0 && typeof value === 'string')
}

/** Validate untrusted renderer input for the license relay: a non-empty
 *  string server plus a flat, non-empty object of non-empty string keys to
 *  string values, whose framed size stays under the control-line cap.
 *  Returns a STATIC error (never echoing any value) or null. */
export function credentialInputError(server: unknown, secrets: unknown): string | null {
  if (typeof server !== 'string' || server.length === 0) return 'invalid server name'
  if (!isFlatStringRecord(secrets)) return 'invalid secrets'
  if (Buffer.byteLength(JSON.stringify(secrets), 'utf8') > MAX_CREDENTIAL_SECRETS_BYTES) {
    return 'secrets too large'
  }
  return null
}

export interface CredentialWriteResult {
  ok: boolean
  error?: string
}

// --- supervision state (module-singleton: one companion per app) -------------

let child: ChildProcess | null = null
let started = false
let stopped = false
let attempt = -1
let spawnedAt = 0
let restartTimer: NodeJS.Timeout | null = null
/** Latest token seen; undefined ⇒ never set, so nothing to replay on spawn. */
let latestToken: string | null | undefined
/**
 * The project this companion serves. Null ⇒ do not spawn at all.
 *
 * The bridge route is `/api/v1/projects/{project_id}/bridge`, and the companion
 * parses that id back OUT of its `SOLUS_COMPANION_URL`, so the project is baked
 * into the child's environment at spawn time — there is no stdin control line
 * to re-point a running one. A project change therefore means a new process.
 *
 * Spawning without a project is worse than not spawning: no URL can be derived,
 * and the companion exits with "SOLUS_COMPANION_URL is required" on every
 * attempt, which is a crash loop rather than an idle bridge.
 */
let activeProjectId: string | null = null

function pidfilePath(): string {
  return join(app.getPath('userData'), 'companion.pid')
}

function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

/** Signal the companion's whole process tree; best-effort on every path. */
function killTree(pid: number, signal: 'SIGTERM' | 'SIGKILL'): void {
  if (process.platform === 'win32') {
    execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => undefined)
    return
  }
  try {
    process.kill(-pid, signal) // detached ⇒ the child leads its own group
  } catch {
    try {
      process.kill(pid, signal)
    } catch {
      /* already gone */
    }
  }
}

/** Best-effort command line of a live pid; null when unreadable. Win32 has no
 *  cheap equivalent here, so it returns null ⇒ the reap is skipped and the
 *  pidfile is simply taken over (documented in companion-packaging.md). */
function readCmdline(pid: number): string | null {
  try {
    if (process.platform === 'linux') return readFileSync(`/proc/${pid}/cmdline`, 'utf8')
    if (process.platform === 'darwin') {
      return execFileSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' })
    }
  } catch {
    /* process vanished or unreadable — treat as not-a-companion */
  }
  return null
}

/** If a previous app run left a live companion behind, terminate its tree so
 *  this run can take over the pidfile. The pid is killed only when its command
 *  line identifies it as the companion — a stale pidfile pid may have been
 *  recycled by the OS to an unrelated process. */
function reapOrphan(): void {
  let pid: number | null = null
  try {
    pid = parsePidfile(readFileSync(pidfilePath(), 'utf8'))
  } catch {
    return // no pidfile — nothing to reap
  }
  if (!shouldReapPid(pid, isPidAlive)) return
  const cmdline = readCmdline(pid as number)
  if (cmdline !== null && isCompanionCmdline(cmdline)) killTree(pid as number, 'SIGTERM')
}

function removePidfile(): void {
  try {
    unlinkSync(pidfilePath())
  } catch {
    /* best-effort */
  }
}

function writeStdin(target: ChildProcess, line: string): void {
  if (!target.stdin?.writable) return
  try {
    target.stdin.write(line)
  } catch {
    /* companion went down mid-write; the token is replayed on the next spawn */
  }
}

/** The API base the companion should dial back to. Same source the renderer
 *  uses, so a build points both at one origin.
 *
 *  Read from `import.meta.env`, NOT `process.env`: Vite inlines env values into
 *  the bundle and never writes them back to `process.env`, so the old
 *  `process.env.VITE_API_BASE_URL` was always undefined and this silently always
 *  returned localhost — a packaged build pointed the companion at localhost
 *  while the renderer talked to the real API. electron-vite applies the same
 *  `VITE_`prefix to the main build (envPrefix `MAIN_VITE_`/`VITE_`), and envDir
 *  is the repo root, so both halves now resolve from the one root `.env`. */
function apiBaseUrl(): string {
  return resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL)
}

function spawnChild(cmd: { command: string; args: string[] }): void {
  restartTimer = null
  if (stopped) return
  const c = spawn(cmd.command, cmd.args, {
    detached: process.platform !== 'win32', // own process group ⇒ tree kill works
    // stderr is PIPED, not ignored. The companion validates its own config and
    // exits; with stderr discarded that surfaced as a silent restart loop and
    // was why the bridge never came up (CAD-02).
    stdio: ['pipe', 'ignore', 'pipe'],
    // Inherited PLUS the variables the companion cannot start without.
    //
    // The integrations root is resolved only for a dev run: a packaged build
    // finds the tree beside its own binary, and passing a path derived from the
    // app directory would override that with something wrong. `null` when
    // nothing resolves, so the companion still reports the missing variable
    // itself instead of running with zero MCP servers.
    env: companionEnv(process.env, apiBaseUrl(), {
      integrationsRoot: app.isPackaged ? null : findIntegrationsRoot(app.getAppPath(), existsSync),
      projectId: activeProjectId,
      // The ~/.solus registry (SOLUSDEV-166 / ADR-034): the project's linked
      // working copy, read fresh at every spawn. Null (variable absent) when
      // the project has no linked folder — workspace-gated forks fail closed.
      workspace: projectWorkspace(activeProjectId, realLocalStateDeps)
    })
  })
  c.stderr?.on('data', (chunk: Buffer) => {
    // Bounded: a crash-looping child must not fill the log.
    console.warn('[companion]', chunk.toString('utf8').slice(0, 2_000).trimEnd())
  })
  child = c
  spawnedAt = Date.now()
  if (c.pid) {
    try {
      writeFileSync(pidfilePath(), String(c.pid))
    } catch {
      /* pidfile is an orphan-reap aid, not a correctness requirement */
    }
  }
  if (latestToken !== undefined) writeStdin(c, tokenLine(latestToken))

  let down = false
  const onDown = (): void => {
    if (down) return
    down = true
    if (child === c) child = null
    if (stopped) return
    attempt = nextRestartAttempt(attempt, Date.now() - spawnedAt)
    restartTimer = setTimeout(() => spawnChild(cmd), backoffDelayMs(attempt))
  }
  c.on('exit', onDown)
  c.on('error', onDown) // spawn failure (e.g. bad dev cmd) retries on the same schedule
}

/** Spawn if — and only if — there is something to serve. Idempotent. */
function maybeSpawn(): void {
  if (stopped || child !== null || activeProjectId === null) return
  const cmd = resolveCompanionCommand({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    platform: process.platform,
    env: process.env
  })
  if (!cmd) {
    console.warn('[companion] disabled: not packaged and SOLUS_COMPANION_DEV_CMD is not set')
    return
  }
  spawnChild(cmd)
}

/** Arm the companion for this app run. It does not spawn until a project is
 *  selected — see `setCompanionProject`. */
export function startCompanion(): void {
  if (started) return
  started = true
  stopped = false
  reapOrphan()
  maybeSpawn()
}

/**
 * Point the companion at a project (null ⇒ none), respawning if it changed.
 *
 * The project is fixed in the child's environment at spawn, so switching means
 * replacing the process. The old child is killed WITHOUT setting `stopped`, so
 * the normal restart path stays available for the new one.
 */
export function setCompanionProject(projectId: string | null): void {
  if (projectId === activeProjectId) return
  activeProjectId = projectId
  replaceChild()
}

/**
 * A project's folder link changed in the ~/.solus registry (SOLUSDEV-166).
 * The workspace is baked into the child's environment at spawn — exactly like
 * the project id — so when it is the ACTIVE project's link that changed, the
 * companion respawns to pick it up. Other projects' links are irrelevant to
 * the running child.
 */
export function notifyProjectFolderChanged(projectId: string): void {
  if (activeProjectId === null || projectId !== activeProjectId) return
  replaceChild()
}

/** Kill the current child (if any) and spawn a fresh one against the current
 *  project + registry state. A deliberate replacement is not a failure, so the
 *  backoff schedule resets to the 1 s step. */
function replaceChild(): void {
  if (restartTimer) {
    clearTimeout(restartTimer)
    restartTimer = null
  }
  const previous = child
  child = null // detach first: onDown must not schedule a restart for the old config
  previous?.kill('SIGTERM')
  attempt = -1
  if (started) maybeSpawn()
}

/** Relay the current access token (null ⇒ signout) to the companion's stdin.
 *  Remembered and replayed on the next spawn when the companion is down.
 *  The token is never logged and never touches disk. */
export function sendAccessToken(token: string | null): void {
  latestToken = token
  if (child) writeStdin(child, tokenLine(token))
}

/** Relay one BYO-license capture (SOLUSDEV-102 / MCP-05) to the companion's
 *  stdin as exactly one newline-terminated JSON line. Unlike tokens, the
 *  secrets are NEVER remembered or replayed — they exist only in this call's
 *  write. Values are never logged; errors are static strings. */
export function writeCredential(server: unknown, secrets: unknown): CredentialWriteResult {
  const invalid = credentialInputError(server, secrets)
  if (invalid !== null) return { ok: false, error: invalid }
  if (!child || !child.stdin?.writable) return { ok: false, error: 'companion not running' }
  try {
    child.stdin.write(credentialLine(server as string, secrets as Record<string, string>))
  } catch {
    // The companion died mid-write; the user re-submits once it restarts.
    return { ok: false, error: 'companion write failed' }
  }
  return { ok: true }
}

/** Stop the companion for good: SIGTERM the tree, give it 3 s, then SIGKILL.
 *  Removes the pidfile and suppresses any further restarts. */
export async function stopCompanion(): Promise<void> {
  stopped = true
  started = false
  if (restartTimer) {
    clearTimeout(restartTimer)
    restartTimer = null
  }
  const c = child
  child = null
  if (c?.pid && c.exitCode === null && c.signalCode === null) {
    const exited = new Promise<void>((resolve) => {
      c.once('exit', () => resolve())
      c.once('error', () => resolve())
    })
    killTree(c.pid, 'SIGTERM')
    const graceful = await Promise.race([
      exited.then(() => true),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), STOP_GRACE_MS))
    ])
    if (!graceful) {
      killTree(c.pid, 'SIGKILL')
      await exited
    }
  }
  removePidfile()
}
