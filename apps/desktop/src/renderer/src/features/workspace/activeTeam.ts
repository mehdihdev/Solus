// The ACTIVE TEAM rule (SOLUSDEV-242 / HOME H1), shared by Home and the Team
// screen so the two can never disagree about which team the workspace is on.
//
// The persisted id (`workspaceStore.teamId`) is a memory of a SERVER row, so it
// is trusted only while it is still one of my teams. It used to win outright
// on the Team screen (`storedTeamId ?? …`), so an id left over from another
// database — or a team I had been removed from — was requested forever, 404ing
// every call while the screen blamed the backend. Pure, so the rule is
// readable and testable on its own.
import { personalTeam, type Me, type TeamSummary } from '../../lib/api/resources'

export function resolveTeamId(me: Me | null, storedTeamId: string | null): string | null {
  if (!me) return null
  const stillMine = me.teams.some((t) => t.team_id === storedTeamId)
  // Still mine ⇒ keep it. Self-healing must not become gratuitous switching:
  // someone who chose a non-personal team stays on it across reloads.
  return stillMine ? storedTeamId : (personalTeam(me)?.team_id ?? null)
}

/** The resolved active team's summary, or null when the user is on no team. */
export function resolveTeam(me: Me | null, storedTeamId: string | null): TeamSummary | null {
  const id = resolveTeamId(me, storedTeamId)
  return (id && me?.teams.find((t) => t.team_id === id)) || null
}
