// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5, narrowed by
// §2.2): may SOL drive for the active project right now? Pure — the filesystem enters only
// through the injected realpath and the caller's helper check.
//
// The nested-folder rule (security review M1 of ADR-041 M2/M3): the helper's
// project binding is "at or below the workspace", so with nested links a step
// for the outer project would pass for a KiCad working on the inner one.
// Driving is therefore unavailable while the active folder equals, contains or
// lies inside ANY other linked project's folder.
import type { DriveUnavailable } from './driveStatus'

/** Case-insensitive volumes are the macOS/Windows default; folding there can
 *  only over-report a conflict, which fails safe. */
function segments(path: string, platform: NodeJS.Platform): string[] {
  const folded = platform === 'linux' ? path : path.toLowerCase()
  return folded.split(/[/\\]+/).filter((s) => s.length > 0)
}

/** `child` is `parent` or lies below it, by whole path segment (`/a/bc` is not
 *  inside `/a/b`). Both should already be canonical. */
export function isAtOrInside(child: string, parent: string, platform: NodeJS.Platform): boolean {
  const c = segments(child, platform)
  const p = segments(parent, platform)
  return p.length <= c.length && p.every((seg, i) => seg === c[i])
}

/** True when the active project's folder equals, contains or lies inside
 *  another project's. An active folder that no longer resolves fails closed;
 *  another project's dead link is ignored (it cannot host a KiCad). */
export function nestedFolderConflict(
  projectId: string,
  folders: Readonly<Record<string, string>>,
  realpath: (path: string) => string | null,
  platform: NodeJS.Platform
): boolean {
  const stored = folders[projectId]
  const active = stored === undefined ? null : realpath(stored)
  if (active === null) return true
  return Object.entries(folders).some(([id, path]) => {
    if (id === projectId) return false
    const other = realpath(path)
    if (other === null) return false
    return isAtOrInside(active, other, platform) || isAtOrInside(other, active, platform)
  })
}

export interface DriveAvailabilityInput {
  platform: NodeJS.Platform
  /** The helper path resolves to an executable file. */
  helperOk: boolean
  /** Packaged: Solus.app's own signature validates (checkOwnBundle). Dev: omitted. */
  bundleOk?: boolean
  projectId: string | null
  /** Every project's linked folder on this machine (validated registry read). */
  folders: Readonly<Record<string, string>>
  realpath: (path: string) => string | null
}

/** Why driving cannot run, in order, or null when it can. */
export function driveUnavailable(input: DriveAvailabilityInput): DriveUnavailable | null {
  if (input.platform !== 'darwin') return 'not_macos'
  if (!input.helperOk) return 'no_helper'
  if (input.bundleOk === false) return 'bundle_modified'
  // §2.2 (ADR-041 2026-10-31): no linked folder only means KiCad (project-
  // bound) is not drivable; window-bound apps need none.
  const { projectId, folders } = input
  if (projectId === null || !Object.hasOwn(folders, projectId)) return null
  if (nestedFolderConflict(projectId, folders, input.realpath, input.platform)) {
    return 'nested_folder'
  }
  return null
}
