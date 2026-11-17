import { useCallback, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import type { Entity, Relation } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { RobotSidebar } from '../sidebar/RobotSidebar'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { RobotNodeContent } from './RobotNodeContent'
import { RobotSession } from './robotSession'
import './robots.css'

const NO_ENTITIES: readonly Entity[] = []
const NO_RELATIONS: readonly Relation[] = []

export function usePhysicalRobots(
  projectId: string | null,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void,
  /** The workspace's current entities.
   *  Must be the snapshot's own array: the sidebar caches its reads by this identity. */
  entities: readonly Entity[] | null = null,
  /** The snapshot's edges — the sidebar's category tree is read from `contains` only. */
  relations: readonly Relation[] = NO_RELATIONS
): {
  renderContent: (entity: Entity) => ReactNode
  /** The robot / category sidebar (SOLUSDEV-250 P4) — no modals, no overlays. */
  renderSidebar: (entity: Entity) => ReactNode
} {
  const mode = useSettingsStore((state) => state.solMode)
  const { session, online, generation } = useRobotSession(projectId, onChanged, onReveal)
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
  useEffect(() => {
    session.activate()
    return session.dispose
  }, [session])
  // Stable identities: the memoised graph cards re-render only when these change.
  const renderContent = useCallback(
    (entity: Entity) => <RobotNodeContent entity={entity} mode={mode} />,
    [mode]
  )
  const renderSidebar = useCallback(
    (entity: Entity) => (
      <RobotSidebar
        key={`${generation}:${entity.id}`}
        entity={entity}
        session={session}
        state={state}
        online={online}
        mode={mode}
        entities={entities ?? NO_ENTITIES}
        relations={relations}
        onChanged={onChanged}
        onReveal={onReveal}
      />
    ),
    [generation, session, state, online, mode, entities, relations, onChanged, onReveal]
  )
  return { renderContent, renderSidebar }
}

function useRobotSession(
  projectId: string | null,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void
): { session: RobotSession; online: boolean; generation: number } {
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const authenticated = useAuthStore((state) => state.status === 'authenticated')
  const generation = useWorkspaceSessionGeneration()
  const online = authenticated && projectId !== null
  const current = useCallback(() => {
    const auth = useAuthStore.getState()
    const workspace = useWorkspaceStore.getState()
    return (
      online &&
      workspaceSessionGeneration() === generation &&
      workspace.project?.id === projectId &&
      auth.status === 'authenticated' &&
      `${auth.status}:${auth.user?.email ?? ''}` === identity
    )
  }, [projectId, generation, identity, online])
  const session = useMemo(
    () => new RobotSession(projectId ?? '', current, onChanged, onReveal),
    [projectId, current, onChanged, onReveal]
  )
  return { session, online, generation }
}
