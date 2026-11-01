// What every bench card needs from the shared view: the view itself, whether this user may
// write it (viewer → read-only, wireflow live-bench-view.md §8), and the live device series
// (plot-group overlays and derived inputs). Null outside the Live Bench screen, where cards
// keep their plain behaviour.
import { createContext, useContext } from 'react'
import type { BenchView } from '@solus/shared-types'
import type { BenchDeviceRecent, Me } from '../../../lib/api/resources'

export interface BenchViewContextValue {
  projectId: string
  view: BenchView | null
  canEdit: boolean
  devices: Readonly<Record<string, BenchDeviceRecent>>
}

export const BenchViewContext = createContext<BenchViewContextValue | null>(null)

export function useBenchViewContext(): BenchViewContextValue | null {
  return useContext(BenchViewContext)
}

const WRITE_ROLES: ReadonlySet<string> = new Set(['owner', 'admin', 'member'])

/** Writes need MEMBER (route doc preamble). Unknown role → read-only; the server decides anyway. */
export function canEditBenchView(me: Me | null, teamId: string): boolean {
  const role = me?.teams?.find((team) => team.team_id === teamId)?.role
  return role !== undefined && WRITE_ROLES.has(role)
}
