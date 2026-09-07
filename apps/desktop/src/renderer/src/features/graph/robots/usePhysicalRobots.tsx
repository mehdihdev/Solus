import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode
} from 'react'
import type { Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { DeleteConfirmModal } from '../../workspace/modals'
import { HardwareAddPanel } from '../hardware'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { RobotNodeContent } from './RobotNodeContent'
import { RobotOrphans } from './RobotOrphans'
import { RobotSession, editableRobot } from './robotSession'
import './robots.css'

export function usePhysicalRobots(
  projectId: string | null,
  revision: number,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void,
  /** The workspace's current entities — the Authored flow lists its physical robots. */
  entities: readonly Entity[] | null = null
): {
  hardware: ReactNode
  renderContent: (entity: Entity) => ReactNode
  overlays: ReactNode
  prompt: ReactNode
} {
  const mode = useSettingsStore((state) => state.solMode)
  const { revealedRef, captureReveal } = useRevealCapture(onReveal)
  const { session, online, generation, current } = useRobotSession(
    projectId,
    onChanged,
    captureReveal
  )
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
  const hardware = useHardwareAdd(session, current, revealedRef, onChanged, entities)
  const [deletion, setDeletion] = useState<{ session: RobotSession; entity: Entity } | null>(null)
  const pending = deletion?.session === session ? deletion.entity : null
  useEffect(() => {
    session.activate()
    return session.dispose
  }, [session])
  useEffect(() => {
    void session.load()
  }, [session, revision])
  const deleteError = pending && state.error?.key === pending.id ? state.error.message : null
  return {
    hardware: (
      <HardwareAddPanel projectId={session.projectId} online={online} mode={mode} {...hardware} />
    ),
    renderContent: (entity) => (
      <RobotNodeContent
        key={`${generation}:${entity.id}`}
        entity={entity}
        session={session}
        state={state}
        online={online}
        mode={mode}
        onDelete={(target) => setDeletion({ session, entity: target })}
      />
    ),
    overlays: pending && (
      <DeleteConfirmModal
        name={pending.name}
        noun="robot"
        detail={`and its seven categories. Its parts and other links will be retained${deleteError ? `. ${deleteError}` : ''}`}
        onClose={() => setDeletion(null)}
        onConfirm={() => session.remove(pending)}
      />
    ),
    prompt: online ? <RobotOrphans session={session} state={state} mode={mode} /> : null
  }
}

// ponytail: RobotSession.create() reveals the new robot but returns only a boolean;
// capture the revealed id rather than widening robotSession.ts (outside R1).
function useRevealCapture(onReveal: (entityId: string) => void): {
  revealedRef: React.RefObject<string | null>
  captureReveal: (entityId: string) => void
} {
  const revealedRef = useRef<string | null>(null)
  const captureReveal = useCallback(
    (entityId: string) => {
      revealedRef.current = entityId
      onReveal(entityId)
    },
    [onReveal]
  )
  return { revealedRef, captureReveal }
}

/** Add › Hardware wiring: the Authored target list, robot creation through the
 *  session, and a refresh that only publishes for the still-current workspace. */
function useHardwareAdd(
  session: RobotSession,
  current: () => boolean,
  revealedRef: React.RefObject<string | null>,
  onChanged: () => void,
  entities: readonly Entity[] | null
): { createRobot: () => Promise<string>; onCreated: () => void; robots: Entity[] } {
  const createRobot = useCallback(async (): Promise<string> => {
    revealedRef.current = null
    const ok = await session.create()
    const id = revealedRef.current
    if (!ok || !id)
      throw new Error(session.snapshot().error?.message ?? 'The robot could not be created.')
    return id
  }, [session, revealedRef])
  const onCreated = useCallback(() => {
    if (current()) onChanged()
  }, [current, onChanged])
  const robots = useMemo(
    () => (entities ?? []).filter((entity) => editableRobot(entity, session.projectId)),
    [entities, session.projectId]
  )
  return { createRobot, onCreated, robots }
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
