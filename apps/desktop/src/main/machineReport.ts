// SOLUSDEV-320 P5-T1d: the machine reporter. MAIN is the only process that
// knows this machine (companion id + hostname/os/arch) AND holds the bearer
// token, so it tells the API which machine the member runs on
// (`PUT /projects/{id}/members/me/machines/{companion_id}`, docs/api/findings.md)
// and mirrors the shared-flagged preferences
// (`PUT /projects/{id}/members/me/preferences`, docs/api/solus.md §2.1).
//
// Triggers are project open and companion (re)spawn; a lane sends at most once
// per MACHINE_REPORT_DEBOUNCE_MS and only when its payload changed since the
// last SUCCESSFUL send. A failure is logged and retried on the next trigger.
// Nothing is persisted: state lives for the app run only.
import type { PreferenceSection } from '@solus/shared-types'
import { HARDWARE_UUID } from './hardwareLocalState'
import { INSTANCE_ID_PATTERN } from './machineIdentity'

export const MACHINE_REPORT_DEBOUNCE_MS = 60_000
// Must stay below the debounce: a lane's send has always settled before its
// window reopens, so two PUTs to one lane can never race (and finish out of order).
const SEND_TIMEOUT_MS = 8_000

export type SharedPreferences = Partial<Record<PreferenceSection, string>>

export interface MachineReporterDeps {
  fetcher: typeof fetch
  identity: () => { id: string; name: string } | null
  platform: () => { os: string; arch: string; hostname: string }
  now: () => number
  /** Run `fn` after `ms`; the returned function cancels it. */
  schedule: (fn: () => void, ms: number) => () => void
  apiBaseUrl: string
}

export interface MachineReporter {
  setToken(token: string | null): void
  setProject(projectId: string | null): void
  onCompanionUp(): void
  sendPreferences(shared: SharedPreferences): void
  stop(): void
}

interface Request {
  path: string
  body: unknown
}

/** One debounced, hash-deduplicated PUT target. */
interface Lane {
  lastHash: string | null
  lastSentAt: number
  inflight: string | null
  cancel: (() => void) | null
}

function newLane(): Lane {
  return { lastHash: null, lastSentAt: Number.NEGATIVE_INFINITY, inflight: null, cancel: null }
}

// ponytail: copy of hardwareSources.authorizedBase — not exported there, and
// that file belongs to another task. https, or http on loopback only.
function authorizedBase(base: URL): boolean {
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)
  return (
    !base.username &&
    !base.password &&
    !base.search &&
    !base.hash &&
    (base.protocol === 'https:' || (base.protocol === 'http:' && loopback))
  )
}

function apiRoot(apiBaseUrl: string): string | null {
  try {
    const base = new URL(apiBaseUrl)
    return authorizedBase(base) ? base.toString().replace(/\/$/u, '') : null
  } catch {
    return null
  }
}

/** Same acceptance as HardwareSources.setToken: never a header-injectable value. */
function validToken(token: string | null): string | null {
  return token !== null && token.length > 0 && token.length <= 16_384 && !/[\r\n]/u.test(token)
    ? token
    : null
}

/** identity() touches ~/.solus (mkdir/chmod/write); a broken home must never
 *  escape into the companion spawn, an IPC handler or the debounce timer. */
function safeBuild(build: () => Request | null): Request | null {
  try {
    return build()
  } catch (error) {
    console.warn('[machine-report] build failed:', error instanceof Error ? error.message : error)
    return null
  }
}

class Reporter implements MachineReporter {
  private readonly root: string | null
  private readonly machine = newLane()
  private readonly prefs = newLane()
  private token: string | null = null
  private projectId: string | null = null
  /** The last explicit save this run; re-mirrored on project open when non-empty. */
  private shared: SharedPreferences | null = null
  private stopped = false

  constructor(private readonly deps: MachineReporterDeps) {
    this.root = apiRoot(deps.apiBaseUrl)
  }

  setToken(next: string | null): void {
    const valid = validToken(next)
    if (valid === this.token) return
    const hadIdentity = this.token !== null
    this.token = valid
    this.cancelAll()
    if (hadIdentity) {
      // Sign-out, or a token relayed straight from account A to account B: forget
      // what was sent AND what was saved, so A's preference sections never mirror
      // under B. Only an explicit save under the new identity mirrors again.
      this.machine.lastHash = null
      this.prefs.lastHash = null
      this.shared = null
    }
    if (this.token === null) return
    this.triggerAll()
  }

  setProject(next: string | null): void {
    const valid = next !== null && HARDWARE_UUID.test(next) ? next : null
    if (valid === this.projectId) return
    this.projectId = valid
    this.cancelAll()
    this.triggerAll()
  }

  onCompanionUp(): void {
    this.trigger(this.machine, this.machineRequest)
  }

  sendPreferences(next: SharedPreferences): void {
    this.shared = next
    this.trigger(this.prefs, this.preferencesRequest)
  }

  stop(): void {
    this.stopped = true
    this.cancelAll()
  }

  private cancelAll(): void {
    for (const lane of [this.machine, this.prefs]) {
      lane.cancel?.()
      lane.cancel = null
    }
  }

  private triggerAll(): void {
    this.trigger(this.machine, this.machineRequest)
    if (this.shared !== null && Object.keys(this.shared).length > 0)
      this.trigger(this.prefs, this.preferencesRequest)
  }

  private readonly machineRequest = (): Request | null => {
    const identity = this.deps.identity()
    if (identity === null || !INSTANCE_ID_PATTERN.test(identity.id)) return null
    const { hostname, os, arch } = this.deps.platform()
    return {
      path: `/projects/${this.projectId}/members/me/machines/${identity.id}`,
      body: { hostname, os, arch }
    }
  }

  private readonly preferencesRequest = (): Request | null =>
    this.shared === null
      ? null
      : {
          path: `/projects/${this.projectId}/members/me/preferences`,
          body: { schema_version: 1, shared: this.shared }
        }

  /** Send now, or once the lane's debounce window has passed — rebuilt at fire time. */
  private trigger(lane: Lane, build: () => Request | null): void {
    if (this.stopped || this.root === null || this.token === null || this.projectId === null) return
    const request = safeBuild(build)
    if (request === null) return
    const hash = JSON.stringify([this.projectId, request.path, request.body])
    if (hash === lane.lastHash || hash === lane.inflight) return
    lane.cancel?.()
    lane.cancel = null
    const wait = lane.lastSentAt + MACHINE_REPORT_DEBOUNCE_MS - this.deps.now()
    if (wait > 0) {
      lane.cancel = this.deps.schedule(() => {
        lane.cancel = null
        this.trigger(lane, build)
      }, wait)
      return
    }
    void this.send(lane, hash, request)
  }

  private async send(lane: Lane, hash: string, request: Request): Promise<void> {
    const bearer = this.token
    lane.inflight = hash
    lane.lastSentAt = this.deps.now()
    try {
      const response = await this.deps.fetcher(`${this.root}${request.path}`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${bearer}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(request.body),
        redirect: 'error',
        signal: AbortSignal.timeout(SEND_TIMEOUT_MS)
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      if (!this.stopped && this.token === bearer) lane.lastHash = hash
    } catch (error) {
      console.warn(
        `[machine-report] PUT ${request.path} failed:`,
        error instanceof Error ? error.message : error
      )
    } finally {
      if (lane.inflight === hash) lane.inflight = null
    }
  }
}

export function startMachineReporter(deps: MachineReporterDeps): MachineReporter {
  return new Reporter(deps)
}
