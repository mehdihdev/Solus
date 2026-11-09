// SOLUSDEV-319 (multi-team Home): each of my teams' member count for the team rail.
// `GET /users/me` lists my teams without sizes, so each team's detail is read once per
// team id (a person belongs to few teams). A failed read leaves that team without a count:
// empty beats invented. `known` overrides with a fresher count (the active team's live roster).
import { useEffect, useRef, useState } from 'react'
import { getTeamDetail } from '../../lib/api/resources'

export type TeamSizes = Readonly<Record<string, number>>

export function useTeamSizes(teamIds: readonly string[], known: TeamSizes = {}): TeamSizes {
  const [sizes, setSizes] = useState<Record<string, number>>({})
  // Every team asked for, once. A ref (kept across StrictMode's re-run) and no per-run
  // cancellation: a reply always lands, so no team is left sizeless or asked again.
  const requested = useRef(new Set<string>())
  const key = teamIds.join(',')

  useEffect(() => {
    for (const id of key ? key.split(',') : []) {
      if (requested.current.has(id)) continue
      requested.current.add(id)
      getTeamDetail(id)
        .then((detail) => setSizes((s) => ({ ...s, [id]: detail.member_count })))
        .catch(() => undefined)
    }
  }, [key])

  return { ...sizes, ...known }
}
