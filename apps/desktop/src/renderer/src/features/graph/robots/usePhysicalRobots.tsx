import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { DeleteConfirmModal } from '../../workspace/modals'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { RobotHardware } from './RobotHardware'
import { RobotNodeContent } from './RobotNodeContent'
import { RobotOrphans } from './RobotOrphans'
import { RobotSession } from './robotSession'
import './robots.css'

export function usePhysicalRobots(
  projectId: string | null,
  revision: number,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void
): {
  hardware: ReactNode
  renderContent: (entity: Entity) => ReactNode
  overlays: ReactNode
  prompt: ReactNode
} {
  const mode = useSettingsStore((state) => state.solMode)
  const { session, online, generation } = useRobotSession(projectId, onChanged, onReveal)
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
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
    hardware: <RobotHardware session={session} state={state} online={online} mode={mode} />,
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

function useRobotSession(
  projectId: string | null,
  onChanged: (removedId?: string) => void,
  onReveal: (entityId: string) => void
): { session: RobotSession; online: boolean; generation: number } {
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const authenticated = useAuthStore((state) => state.status === 'authenticated')
  const generation = useWorkspaceSessionGeneration()
  const online = authenticated && projectId !== null
  const session = useMemo(
    () =>
      new RobotSession(
        projectId ?? '',
        () => {
          const auth = useAuthStore.getState()
          const workspace = useWorkspaceStore.getState()
          return (
            online &&
            workspaceSessionGeneration() === generation &&
            workspace.project?.id === projectId &&
            auth.status === 'authenticated' &&
            `${auth.status}:${auth.user?.email ?? ''}` === identity
          )
        },
        onChanged,
        onReveal
      ),
    [projectId, generation, identity, online, onChanged, onReveal]
  )
  return { session, online, generation }
}
