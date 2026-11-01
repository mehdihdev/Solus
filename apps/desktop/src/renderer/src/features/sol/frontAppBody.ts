// SOLUSDEV-319 slice 4 (API-implementation.md `front_app`, sol-drive.md §2.2):
// main's front-app snapshot → the turn body's strict `front_app`. The API
// model forbids unknown keys and requires every key, so absent values are
// explicit nulls (a denied app: no title, pid, window id or binding). Pure.
import type { SolFrontApp } from '../../../../main/drive/frontAppShape'

export interface FrontAppBody {
  readonly bundle_id: string
  readonly name: string
  readonly title: string | null
  readonly pid: number | null
  readonly window_id: number | null
  readonly drivable: boolean
  readonly binding: 'project' | 'window' | null
}

export function toFrontAppBody(front: SolFrontApp): FrontAppBody {
  const common = { bundle_id: front.bundleId, name: front.name, binding: front.binding }
  if (!front.drivable) {
    return { ...common, title: null, pid: null, window_id: null, drivable: false }
  }
  return {
    ...common,
    title: front.title,
    pid: front.pid,
    window_id: front.windowId,
    drivable: true
  }
}
