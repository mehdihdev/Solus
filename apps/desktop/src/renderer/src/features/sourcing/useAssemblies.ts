// SOLUSDEV-246 (STORE ST5) — the project's CAD assemblies (parts flagged
// `is_assembly` by the CAD connector), for the "From CAD" requirement.
import { useEffect, useState } from 'react'
import { listEntities, type Entity } from '../../lib/api/resources'

const ASSEMBLY_LIMIT = 200

export function isAssembly(entity: Entity): boolean {
  return entity.type === 'part' && entity.properties?.is_assembly === true
}

export function useAssemblies(projectId: string, enabled: boolean): Entity[] | null {
  const [assemblies, setAssemblies] = useState<Entity[] | null>(null)
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    listEntities(projectId, { type: 'part', limit: ASSEMBLY_LIMIT }).then(
      (rows) => {
        if (!cancelled) setAssemblies(rows.filter(isAssembly))
      },
      () => {
        if (!cancelled) setAssemblies([])
      }
    )
    return () => {
      cancelled = true
    }
  }, [projectId, enabled])
  return assemblies
}
