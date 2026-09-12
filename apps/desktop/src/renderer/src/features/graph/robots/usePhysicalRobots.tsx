import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode
} from 'react'
import type { Entity, Relation } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { HardwareAddPanel } from '../hardware'
import { RobotSidebar } from '../sidebar/RobotSidebar'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { RobotNodeContent } from './RobotNodeContent'
import { RobotSession, editableRobot } from './robotSession'
import './robots.css'

const NO_ENTITIES: readonly Entity[] = []
const NO_RELATIONS: readonly Relation[] = []

export function usePhysicalRobots(
  projectId: string | null,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void,
  /** The workspace's current entities — Add › Hardware lists its robots and reads bindings.
   *  Must be the snapshot's own array: the sidebar caches its reads by this identity. */
  entities: readonly Entity[] | null = null,
  /** The snapshot's edges — the sidebar's category tree is read from `contains` only. */
  relations: readonly Relation[] = NO_RELATIONS,
  /** The entity a surface just received — shown optimistically until the refetch lands (P6). */
  onCreated?: (entity: Entity) => void
): {
  hardware: ReactNode
  renderContent: (entity: Entity) => ReactNode
  /** The robot / category sidebar (SOLUSDEV-250 P4) — no modals, no overlays. */
  renderSidebar: (entity: Entity) => ReactNode
} {
  const mode = useSettingsStore((state) => state.solMode)
  const { session, online, generation, current } = useRobotSession(projectId, onChanged, onReveal)
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
  const hardware = useHardwareAdd(session, current, onChanged, onReveal, entities, onCreated)
  useEffect(() => {
    session.activate()
    return session.dispose
  }, [session])
  // Stable identities: the memoised graph cards re-render only when these change.
  const panel = useMemo(
    () => (
      <HardwareAddPanel projectId={session.projectId} online={online} mode={mode} {...hardware} />
    ),
    [session.projectId, online, mode, hardware]
  )
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
  return { hardware: panel, renderContent, renderSidebar }
}

/** Add › Hardware wiring: the robot target list, the entities the device cards read,
 *  and a refresh that only publishes for the still-current workspace. */
function useHardwareAdd(
  session: RobotSession,
  current: () => boolean,
  onChanged: () => void,
  onReveal: (entityId: string) => void,
  entities: readonly Entity[] | null,
  onOptimistic?: (entity: Entity) => void
): {
  onCreated: (entity: Entity) => void
  robots: Entity[]
  entities: readonly Entity[] | null
} {
  // The surfaces write through the plain client, so an unmounted panel must not publish.
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const onCreated = useCallback(
    (entity: Entity) => {
      if (!mounted.current || !current()) return
      // A part has no containment edge yet; only a robot (a root) can be shown early.
      if (entity.type === 'physical_robot') onOptimistic?.(entity)
      onChanged()
      onReveal(entity.id)
    },
    [current, onChanged, onReveal, onOptimistic]
  )
  const robots = useMemo(
    () => (entities ?? []).filter((entity) => editableRobot(entity, session.projectId)),
    [entities, session.projectId]
  )
  return useMemo(() => ({ onCreated, robots, entities }), [onCreated, robots, entities])
}

function useRobotSession(
  projectId: string | null,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void
): { session: RobotSession; online: boolean; generation: number; current: () => boolean } {
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
  return { session, online, generation, current }
}
