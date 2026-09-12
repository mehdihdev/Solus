// Optimistic entities (SOLUSDEV-250 P6): the entity a surface just received from
// the wire (ConfirmOut.robot, PlatformImportOut.robot, HardwarePartOut.entity …)
// is shown at once, exactly as given, until the authoritative snapshot carries
// its id — or 30 s pass. Never invented, never renamed.
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Entity } from '../../lib/api/resources'

export const OPTIMISTIC_MAX_AGE_MS = 30_000

interface Pending {
  entity: Entity
  expiresAt: number
}

export function useOptimisticGraph(authoritative: readonly Entity[] | null): {
  entities: readonly Entity[]
  add: (entity: Entity) => void
} {
  const [pending, setPending] = useState<readonly Pending[]>([])
  const add = useCallback((entity: Entity) => {
    setPending((current) => [
      ...current.filter((item) => item.entity.id !== entity.id),
      { entity, expiresAt: Date.now() + OPTIMISTIC_MAX_AGE_MS }
    ])
  }, [])
  useEffect(() => {
    if (!authoritative || pending.length === 0) return
    const known = new Set(authoritative.map((entity) => entity.id))
    if (pending.some((item) => known.has(item.entity.id)))
      setPending((current) => current.filter((item) => !known.has(item.entity.id)))
  }, [authoritative, pending])
  useEffect(() => {
    if (pending.length === 0) return
    const next = Math.min(...pending.map((item) => item.expiresAt))
    const timer = setTimeout(
      () => setPending((current) => current.filter((item) => item.expiresAt > Date.now())),
      Math.max(0, next - Date.now())
    )
    return () => clearTimeout(timer)
  }, [pending])
  const entities = useMemo(() => pending.map((item) => item.entity), [pending])
  return { entities, add }
}
