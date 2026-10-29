// SOLUSDEV-319 drive slices 3/3b (docs/architecture/sol-drive.md §5): owns the
// DriveStatus main hands the renderer (Settings › SOL "SOL can use your mouse
// and keyboard") and decides what the companion and the agent may get. The
// setting is the consent; availability is re-evaluated on every setting,
// project or folder link change. Each time, the agent is (un)registered and
// the companion re-checks (it respawns
// only when what it baked actually differs).
import { driveUnavailable } from './driveAvailability'
import type { DriveTrustResult } from './driveHelper'
import type { DriveAgentState, DriveStatus, DriveUnavailable } from './driveStatus'

/** `getDriveStatus` runs on render; this keeps it from asking the agent each time. */
export const DRIVE_TRUST_CACHE_MS = 10_000
/** While a grant is missing the user is likely in System Settings granting it:
 *  getDriveStatus (the renderer calls it on window focus) asks again after
 *  this floor rather than serving a stale "missing" for the full window. The
 *  floor only absorbs a render burst. */
export const DRIVE_MISSING_GRANT_REFRESH_MS = 1_000

export interface DriveSettingsPort {
  get(): { drive: boolean }
  setDrive(on: boolean): void
  onChange(cb: (state: { drive: boolean }) => void): () => void
}

export interface DriveControllerDeps {
  platform: NodeJS.Platform
  /** The agent is installed: packaged — SolusInput.app's helper and the
   *  LaunchAgents plist are in the bundle; dev — the debug helper resolves and
   *  passes the helper path rule. False ⇒ `no_helper`. */
  installed(): boolean
  /** Packaged: the latest checkOwnBundle answer (false until one completed).
   *  Omitted in dev. False ⇒ `bundle_modified`. */
  bundleOk?(): boolean
  /** `trust` through the drive transport (XPC packaged, debug helper in dev). */
  trust(prompt: boolean): Promise<DriveTrustResult | null>
  /** The SMAppService registration (null in dev, where main runs the helper). */
  agentState(): DriveAgentState | null
  /** The setting is on AND the helper is installed: register the agent (true)
   *  or unregister it (false). Called on every re-evaluation. */
  onAgentWanted(wanted: boolean): void
  /** Every project's validated linked folder (localState.linkedWorkspaces). */
  linkedFolders(): Record<string, string>
  realpath(path: string): string | null
  settings: DriveSettingsPort
  now(): number
  broadcast(status: DriveStatus): void
  /** The companion should re-check `companionDrive` against what it spawned with. */
  onCompanionDriveChanged(): void
}

export interface DriveController {
  setProject(projectId: string | null): void
  /** May the companion for `projectId` drive: on AND available. */
  companionDrive(projectId: string | null): boolean
  status(): Promise<DriveStatus>
  setDrive(on: boolean): Promise<DriveStatus>
  requestPermissions(): Promise<DriveStatus>
  /** A folder link (any project's) or another input changed. */
  refresh(): void
}

const cacheLifetime = (result: DriveTrustResult): number =>
  result.trust.accessibility && result.trust.screenRecording
    ? DRIVE_TRUST_CACHE_MS
    : DRIVE_MISSING_GRANT_REFRESH_MS

export function createDriveController(deps: DriveControllerDeps): DriveController {
  let projectId: string | null = null
  let cache: { at: number; result: DriveTrustResult } | null = null
  let lastBroadcast: string | null = null
  let inflight: Promise<DriveTrustResult | null> | null = null

  const reasonFor = (id: string | null): DriveUnavailable | null =>
    driveUnavailable({
      platform: deps.platform,
      helperOk: deps.platform === 'darwin' && deps.installed(),
      bundleOk: deps.bundleOk?.(),
      projectId: id,
      folders: deps.linkedFolders(),
      realpath: deps.realpath
    })

  const wanted = (reason: DriveUnavailable | null): boolean =>
    reason === null && deps.settings.get().drive
  /** The agent depends only on the setting and the install (ADR-041 amendment 3b:
   *  "registered only while the setting is on"), never on the active project —
   *  switching to a project without a usable folder must not unregister it. */
  const agentWanted = (reason: DriveUnavailable | null): boolean =>
    deps.settings.get().drive && reason !== 'not_macos' && reason !== 'no_helper'

  const cachedTrust = async (): Promise<DriveTrustResult | null> => {
    if (cache && deps.now() - cache.at < cacheLifetime(cache.result)) return cache.result
    // One request at a time: a render burst shares the one in flight.
    if (inflight === null) {
      const run = deps.trust(false).then((result) => {
        if (inflight !== run) return result
        inflight = null
        cache = result ? { at: deps.now(), result } : null
        return result
      })
      inflight = run
    }
    return inflight
  }

  const compose = (
    reason: DriveUnavailable | null,
    trust: DriveTrustResult | null
  ): DriveStatus => ({
    enabled: deps.settings.get().drive,
    available: reason === null,
    reason,
    trust: trust?.trust ?? null,
    unsignedDev: trust?.unsignedDev ?? false,
    // L3: shown while on and installed, even for a project that cannot drive,
    // so a requires_approval stays visible.
    agent: agentWanted(reason) ? deps.agentState() : null
  })

  /** Trust is asked only while the agent should be running (on AND installed). */
  const status = async (): Promise<DriveStatus> => {
    const reason = reasonFor(projectId)
    return compose(reason, agentWanted(reason) ? await cachedTrust() : null)
  }

  const publish = (next: DriveStatus): DriveStatus => {
    const key = JSON.stringify(next)
    if (key !== lastBroadcast) {
      lastBroadcast = key
      deps.broadcast(next)
    }
    return next
  }

  const refresh = (): void => {
    deps.onAgentWanted(agentWanted(reasonFor(projectId)))
    deps.onCompanionDriveChanged()
    void status().then(publish)
  }

  deps.settings.onChange(refresh)

  return {
    setProject(id) {
      projectId = id
      refresh()
    },
    companionDrive(id) {
      return wanted(reasonFor(id))
    },
    status: () => status().then(publish),
    async setDrive(on) {
      deps.settings.setDrive(on) // onChange → refresh (agent, companion, broadcast)
      return status().then(publish)
    },
    async requestPermissions() {
      const reason = reasonFor(projectId)
      if (!agentWanted(reason)) return publish(compose(reason, null))
      inflight = null // a plain request finishing later must not overwrite the prompt's answer
      const result = await deps.trust(true)
      // Not cached: the prompt answers before the user acts on it, so the next
      // status (focus back from System Settings) must ask again.
      cache = null
      return publish(compose(reason, result))
    },
    refresh
  }
}
