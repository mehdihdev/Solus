import { useCallback, useMemo, useRef, useState } from 'react'
import type { Point } from '../../../lib/api/workspace'
import type { MoveOrigin } from '../useWorkspaceLayout'
import { isAccountAnchor } from '../accountAnchors'
import { boundedPoint } from './layout'

function read(key: string | null): Record<string, Point> {
  if (!key) return {}
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(
      Object.entries(value)
        .filter(([id, point]) => {
          if (!isAccountAnchor(id) || !point || typeof point !== 'object') return false
          const candidate = point as Partial<Point>
          return (
            typeof candidate.x === 'number' &&
            typeof candidate.y === 'number' &&
            Number.isFinite(candidate.x) &&
            Number.isFinite(candidate.y) &&
            Math.abs(candidate.x) <= 100_000 &&
            Math.abs(candidate.y) <= 100_000
          )
        })
        .slice(0, 256)
    ) as Record<string, Point>
  } catch {
    return {}
  }
}

/** Presentation keys never enter the graph API. Parent remounts on session generation. */
export function useGroupPositions(
  projectId: string,
  email: string | undefined,
  positions: Record<string, Point>,
  onMove: (id: string, point: Point, origin?: MoveOrigin) => void
): {
  positions: Record<string, Point>
  move: (id: string, point: Point, origin?: MoveOrigin) => void
  error: string | null
} {
  const key = email
    ? `solus:graph-groups:v1:${encodeURIComponent(email)}:${encodeURIComponent(projectId)}`
    : null
  const [groups, setGroups] = useState(() => read(key))
  const currentGroups = useRef(groups)
  const [error, setError] = useState<string | null>(null)
  const move = useCallback(
    (id: string, point: Point, origin?: MoveOrigin): void => {
      if (!isAccountAnchor(id)) {
        // Forward the origin only when given: a user drag stays a two-argument call.
        if (origin) onMove(id, point, origin)
        else onMove(id, point)
        return
      }
      const next = Object.fromEntries(
        Object.entries({ ...currentGroups.current, [id]: boundedPoint(point) }).slice(-256)
      )
      currentGroups.current = next
      setGroups(next)
      try {
        if (key) localStorage.setItem(key, JSON.stringify(next))
        setError(key ? null : 'Sign in to save account group positions.')
      } catch {
        setError('Account group position could not be saved locally.')
      }
    },
    [key, onMove]
  )
  return {
    positions: useMemo(() => ({ ...positions, ...groups }), [positions, groups]),
    move,
    error
  }
}
