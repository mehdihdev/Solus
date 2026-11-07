// Words and order shared by Home's team rail, team overview and team menu (SOLUSDEV-319).
import type { TeamSummary } from '../../lib/api/resources'
import type { TeamLimitPosition } from '../../lib/api/planLimit'

/** Collaborative teams first (as the API orders them), the personal workspace last. */
export function railOrder(teams: readonly TeamSummary[]): TeamSummary[] {
  return [...teams.filter((t) => !t.is_personal), ...teams.filter((t) => t.is_personal)]
}

export function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

export function teamInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  const letters = words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)
  return letters.toUpperCase()
}

/** The proactive limit line: "2 of 2 collaborative teams on your plan". */
export function teamLimitText(limit: TeamLimitPosition | null): string | null {
  if (!limit || limit.max === null) return null
  return `${limit.current} of ${limit.max} collaborative teams on your plan · your personal team never counts`
}

/** The same sentence the server refuses with (services/limits.py) — no client
 *  claim about what an upgrade buys. */
export const AT_LIMIT_MESSAGE =
  "You're at your collaborative-team limit. Leave a team or upgrade your plan."
