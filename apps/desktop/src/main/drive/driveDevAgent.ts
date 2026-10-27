// SOLUSDEV-319 drive slice 3b (docs/architecture/sol-drive.md §5 "Main and the
// agent"): a dev run has no SMAppService registration, so main runs the
// resolved debug helper itself as `serve --socket-dir <…/Solus/drive-dev>`
// while drive is wanted — argument list, no shell, PATH-only environment — and
// stops it when not. A child that dies is restarted with backoff. The grants
// then belong to whatever launched the app, as in slices 1–2.

const SERVE_ENV = { PATH: '/usr/bin:/bin' } as const
const BACKOFF_BASE_MS = 1_000
const BACKOFF_CAP_MS = 30_000
/** A child that ran this long resets the backoff. */
const STABLE_RUN_MS = 60_000

export function devAgentRestartDelayMs(attempt: number): number {
  return Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** attempt)
}

/** The slice of a ChildProcess the supervisor needs. */
export interface DevAgentChild {
  on(event: 'exit' | 'error', listener: () => void): unknown
  kill(signal: 'SIGTERM'): boolean
}

export interface DevAgentDeps {
  spawn(
    command: string,
    args: string[],
    options: { env: Record<string, string>; stdio: 'ignore'; shell: false }
  ): DevAgentChild
  /** Make sure the socket directory's parent exists (the agent creates and
   *  checks the directory itself). */
  prepareDir(socketDir: string): void
  setTimeout(cb: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
  now(): number
}

export interface DevAgentWant {
  helper: string
  socketDir: string
}

export interface DevAgentSupervisor {
  /** Run this helper as the agent (null: stop it). */
  set(want: DevAgentWant | null): void
}

const sameWant = (a: DevAgentWant | null, b: DevAgentWant | null): boolean =>
  a?.helper === b?.helper && a?.socketDir === b?.socketDir

export function createDevAgentSupervisor(deps: DevAgentDeps): DevAgentSupervisor {
  let want: DevAgentWant | null = null
  let child: DevAgentChild | null = null
  let timer: unknown = null
  let attempt = 0
  let startedAt = 0

  const scheduleRestart = (): void => {
    const delay = devAgentRestartDelayMs(attempt)
    attempt += 1
    timer = deps.setTimeout(() => {
      timer = null
      start()
    }, delay)
  }

  const start = (): void => {
    if (want === null) return
    const current = want
    try {
      deps.prepareDir(current.socketDir)
      child = deps.spawn(current.helper, ['serve', '--socket-dir', current.socketDir], {
        env: { ...SERVE_ENV },
        stdio: 'ignore',
        shell: false
      })
    } catch {
      child = null
      return scheduleRestart()
    }
    const mine = child
    startedAt = deps.now()
    let down = false
    const onDown = (): void => {
      if (down || child !== mine) return
      down = true
      child = null
      if (deps.now() - startedAt >= STABLE_RUN_MS) attempt = 0
      if (want !== null) scheduleRestart()
    }
    mine.on('exit', onDown)
    mine.on('error', onDown)
  }

  const stop = (): void => {
    if (timer !== null) deps.clearTimeout(timer)
    timer = null
    const previous = child
    child = null // detach first: its exit must not schedule a restart
    try {
      previous?.kill('SIGTERM')
    } catch {
      /* already gone */
    }
  }

  return {
    set(next) {
      if (sameWant(want, next)) return
      stop()
      want = next
      attempt = 0
      start()
    }
  }
}
