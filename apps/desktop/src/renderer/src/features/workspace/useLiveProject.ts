// Keep the open project's name (top bar / switcher) in step with the server
// (ADR-037). A live project-detail hint — `project.updated` on the project
// channel, or `team.projects_changed` naming this project on the account
// channel — only says the detail moved; this refetches it. A project that was
// archived or deleted closes the same way the one-shot validator closes it.
import { useCallback } from 'react'
import { getProject } from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { useAuthStore } from '../../store/authStore'
import { liveKeys } from '../../store/liveRevisionStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useLiveRefetch } from '../live/useLiveRefetch'
import { renameWorkspaceProject, switchWorkspaceProject } from './projectSwitch'

const isOpen = (projectId: string): boolean =>
  useWorkspaceStore.getState().project?.id === projectId

export function useLiveProject(): void {
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated')
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const refetch = useCallback(async () => {
    if (!projectId) return
    try {
      const detail = await getProject(projectId)
      // Re-read: the user may have switched projects while this was in flight.
      if (!isOpen(projectId)) return
      if (detail.archived_at) switchWorkspaceProject(null, 'validation')
      else if (useWorkspaceStore.getState().project?.name !== detail.name)
        renameWorkspaceProject(detail.name)
    } catch (error: unknown) {
      // ONLY a 404 means gone (see useValidateProject); a blip keeps the project.
      if (classifyFetchError(error) === 'gone' && isOpen(projectId))
        switchWorkspaceProject(null, 'validation')
    }
  }, [projectId])
  useLiveRefetch(
    [projectId ? liveKeys.projectDetail(projectId) : null],
    () => void refetch(),
    isAuthenticated && projectId !== null
  )
}
