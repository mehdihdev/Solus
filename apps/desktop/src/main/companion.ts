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
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
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

function spawnChild(cmd: { command: string; args: string[] }): void {
  restartTimer = null
  if (stopped) return
  const c = spawn(cmd.command, cmd.args, {
    detached: process.platform !== 'win32', // own process group ⇒ tree kill works
    stdio: ['pipe', 'ignore', 'ignore'],
    env: process.env
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

/** Start (once) the companion for this app run. No-op when already started or
 *  when no command resolves (dev without SOLUS_COMPANION_DEV_CMD). */
export function startCompanion(): void {
  if (started) return
  started = true
  stopped = false
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
  reapOrphan()
  spawnChild(cmd)
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
