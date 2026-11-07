// SOLUSDEV-319 (multi-team Home): each of my teams' member count for the team rail.
// `GET /users/me` lists my teams without sizes, so each team's detail is read once per
// team id (a person belongs to few teams). A failed read leaves that team without a count:
// empty beats invented. `known` overrides with a fresher count (the active team's live roster).
import { useEffect, useState } from 'react'
import { getTeamDetail } from '../../lib/api/resources'

export type TeamSizes = Readonly<Record<string, number>>

export function useTeamSizes(teamIds: readonly string[], known: TeamSizes = {}): TeamSizes {
  const [sizes, setSizes] = useState<Record<string, number>>({})
  const key = teamIds.join(',')
  // Only a team whose count has LANDED is skipped: a run whose reply was thrown away (a
  // StrictMode re-run, a remount) asks again rather than leaving the team without a size.
  const missing = (key ? key.split(',') : []).filter((id) => !(id in sizes)).join(',')

  useEffect(() => {
    let live = true
    for (const id of missing ? missing.split(',') : []) {
      getTeamDetail(id)
        .then((detail) => {
          if (live) setSizes((s) => ({ ...s, [id]: detail.member_count }))
        })
        .catch(() => undefined)
    }
    return () => {
      live = false
    }
  }, [missing])

  return { ...sizes, ...known }
}
