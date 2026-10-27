// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): owns the
// DriveStatus main hands the renderer (Settings › SOL "SOL can use your mouse
// and keyboard") and decides what the companion may get. The setting is the
// consent; availability is re-evaluated on every setting, project or folder
// link change, and the companion is told to re-check each time (it respawns
// only when what it baked actually differs).
import { driveUnavailable } from './driveAvailability'
import type { DriveTrustResult } from './driveHelper'
import type { DriveStatus, DriveUnavailable } from './driveStatus'

/** `getDriveStatus` runs on render; this keeps it from spawning the helper each time. */
export const DRIVE_TRUST_CACHE_MS = 10_000

export interface DriveSettingsPort {
  get(): { drive: boolean }
  setDrive(on: boolean): void
  onChange(cb: (state: { drive: boolean }) => void): () => void
}

export interface DriveControllerDeps {
  platform: NodeJS.Platform
  /** The resolved helper path (packaged launcher / dev debug build), or null. */
  helperPath(): string | null
  /** A regular file the user may execute. */
  isExecutable(path: string): boolean
  /** Every project's validated linked folder (localState.linkedWorkspaces). */
  linkedFolders(): Record<string, string>
  realpath(path: string): string | null
  runTrust(helper: string, prompt: boolean): Promise<DriveTrustResult | null>
  settings: DriveSettingsPort
  now(): number
  broadcast(status: DriveStatus): void
  /** The companion should re-check `companionDrive` against what it spawned with. */
  onCompanionDriveChanged(): void
}

export interface DriveController {
  setProject(projectId: string | null): void
  /** What the companion for `projectId` may get: on AND available, else null. */
  companionDrive(projectId: string | null): { helper: string } | null
  status(): Promise<DriveStatus>
  setDrive(on: boolean): Promise<DriveStatus>
  requestPermissions(): Promise<DriveStatus>
  /** A folder link (any project's) or another input changed. */
  refresh(): void
}

interface Availability {
  helper: string | null
  reason: DriveUnavailable | null
}

export function createDriveController(deps: DriveControllerDeps): DriveController {
  let projectId: string | null = null
  let cache: { helper: string; at: number; result: DriveTrustResult } | null = null
  let lastBroadcast: string | null = null
  let inflight: { helper: string; run: Promise<DriveTrustResult | null> } | null = null

  const availability = (id: string | null): Availability => {
    const helper = deps.platform === 'darwin' ? deps.helperPath() : null
    const reason = driveUnavailable({
      platform: deps.platform,
      helperOk: helper !== null && deps.isExecutable(helper),
      projectId: id,
      folders: deps.linkedFolders(),
      realpath: deps.realpath
    })
    return { helper: reason === null ? helper : null, reason }
  }

  const trustFor = async (helper: string): Promise<DriveTrustResult | null> => {
    if (cache && cache.helper === helper && deps.now() - cache.at < DRIVE_TRUST_CACHE_MS) {
      return cache.result
    }
    // One run at a time: a render burst shares the spawn in flight.
    if (inflight?.helper !== helper) {
      const run = deps.runTrust(helper, false).then((result) => {
        if (inflight?.run !== run) return result
        inflight = null
        cache = result ? { helper, at: deps.now(), result } : null
        return result
      })
      inflight = { helper, run }
    }
    return inflight.run
  }

  const compose = (a: Availability, trust: DriveTrustResult | null): DriveStatus => ({
    enabled: deps.settings.get().drive,
    available: a.reason === null,
    reason: a.reason,
    trust: trust?.trust ?? null,
    unsignedDev: trust?.unsignedDev ?? false
  })

  const status = async (): Promise<DriveStatus> => {
    const a = availability(projectId)
    return compose(a, a.helper === null ? null : await trustFor(a.helper))
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
      if (!deps.settings.get().drive) return null
      const { helper } = availability(id)
      return helper === null ? null : { helper }
    },
    status: () => status().then(publish),
    async setDrive(on) {
      deps.settings.setDrive(on) // onChange → refresh (companion + broadcast)
      return status().then(publish)
    },
    async requestPermissions() {
      const a = availability(projectId)
      if (a.helper === null) return publish(compose(a, null))
      inflight = null // a plain run finishing later must not overwrite the prompt's answer
      const result = await deps.runTrust(a.helper, true)
      cache = result ? { helper: a.helper, at: deps.now(), result } : null
      return publish(compose(a, result))
    },
    refresh
  }
}
