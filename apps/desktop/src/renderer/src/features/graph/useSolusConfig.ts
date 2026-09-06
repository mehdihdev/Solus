// The project `.solus` for the Workspace panel (SOLUSDEV-240): one GET, five
// sections, refetched after every mutation. Degrades honestly — `offline` when
// no project is linked or the API cannot answer; never a fabricated section.
import { useCallback, useEffect, useState } from 'react'
import {
  getSolus,
  SOLUS_SECTIONS,
  type SolusConfig,
  type SolusEntry,
  type SolusSection
} from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export const SECTION_LABELS: Readonly<Record<SolusSection, string>> = {
  hardware: 'Hardware configs',
  details: 'Project details',
  errors: 'Error logging',
  docs: 'Documentation',
  code: 'Code environment'
}

export type SolusStatus = 'loading' | 'ready' | 'offline'

export interface SolusState {
  status: SolusStatus
  entityId: string | null
  sections: Record<SolusSection, SolusEntry[]>
  /** Re-read the sections; resolves with the fresh config, or null when it failed. */
  refetch: () => Promise<SolusConfig | null>
}

export function emptySections(): Record<SolusSection, SolusEntry[]> {
  const out = {} as Record<SolusSection, SolusEntry[]>
  for (const section of SOLUS_SECTIONS) out[section] = []
  return out
}

/** Shared, never mutated: what every non-ready state shows. */
const EMPTY = emptySections()

interface Snapshot {
  projectId: string
  status: 'ready' | 'offline'
  entityId: string | null
  sections: Record<SolusSection, SolusEntry[]>
}

/** One read, shaped for the hook. Module-level so the effect only ever sets
 *  state from a promise callback (react-hooks/set-state-in-effect). */
async function loadSnapshot(
  projectId: string
): Promise<{ snapshot: Snapshot; config: SolusConfig | null }> {
  try {
    const config = await getSolus(projectId)
    return {
      config,
      snapshot: {
        projectId,
        status: 'ready',
        entityId: config.entity_id,
        sections: config.sections
      }
    }
  } catch {
    return {
      config: null,
      snapshot: { projectId, status: 'offline', entityId: null, sections: EMPTY }
    }
  }
}

export function useSolusConfig(projectId: string | null): SolusState {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const enabled = fetchEnabled && projectId !== null
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)

  const refetch = useCallback(async (): Promise<SolusConfig | null> => {
    if (!enabled || projectId === null) return null
    const loaded = await loadSnapshot(projectId)
    setSnapshot(loaded.snapshot)
    return loaded.config
  }, [enabled, projectId])

  useEffect(() => {
    if (!enabled || projectId === null) return
    let cancelled = false
    void loadSnapshot(projectId).then((loaded) => {
      if (!cancelled) setSnapshot(loaded.snapshot)
    })
    return () => {
      cancelled = true
    }
  }, [enabled, projectId])

  if (!enabled || projectId === null) {
    return { status: 'offline', entityId: null, sections: EMPTY, refetch }
  }
  // A snapshot for another project is stale, not "loaded": loading until ours lands.
  if (snapshot === null || snapshot.projectId !== projectId) {
    return { status: 'loading', entityId: null, sections: EMPTY, refetch }
  }
  return { ...snapshot, refetch }
}
