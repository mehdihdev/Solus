// Plan limits as the server states them (SOLUSDEV-244 / HOME H5; ADR-023).
//
// A limit refusal is `409 plan_limit_reached` with a details block
// `{limit, current, max, upgrade, manage_teams}` (services/limits.py). The
// desktop used to fold every 409 into "unreachable" and tell the user to try
// again; these helpers read the block so the UI can say what the limit is and
// where the upgrade lives. Only the CODE is trusted to mean "limit" — the
// details are validated field by field and degrade to null.
import { ApiError } from './envelope.types'
import type { TeamSummary } from './resources'

export interface PlanLimitRefusal {
  /** Which limit: `max_teams`, `max_projects`, `max_integrations`, or null. */
  limit: string | null
  current: number | null
  max: number | null
  /** The server's own sentence, safe to show. */
  message: string
}

function asInt(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null
}

/** The limit the server refused on, or null when the error is anything else. */
export function planLimitFromError(error: unknown): PlanLimitRefusal | null {
  if (!(error instanceof ApiError) || error.code !== 'plan_limit_reached') return null
  const first = error.details?.[0]
  const block =
    typeof first === 'object' && first !== null ? (first as Record<string, unknown>) : {}
  return {
    limit: typeof block.limit === 'string' ? block.limit : null,
    current: asInt(block.current),
    max: asInt(block.max),
    message: error.message
  }
}

export interface TeamLimitPosition {
  /** Collaborative teams I belong to — the personal team never counts (ADR-025). */
  current: number
  /** null ⇒ unlimited (PRO / an Enterprise override). */
  max: number | null
  atLimit: boolean
}

/** Where I stand against my plan's team limit, from data I already hold.
 *  Null until the subscription's limits are known — nothing is guessed. */
export function teamLimitPosition(
  teams: readonly TeamSummary[],
  limits: Record<string, number | null> | null
): TeamLimitPosition | null {
  if (limits === null) return null
  const current = teams.filter((t) => !t.is_personal).length
  const max = asInt(limits.max_teams)
  return { current, max, atLimit: max !== null && current >= max }
}
