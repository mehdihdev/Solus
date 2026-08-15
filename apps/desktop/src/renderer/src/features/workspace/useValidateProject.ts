// Confirm the persisted current project still exists, once per session.
//
// `workspaceStore` remembers the open project in localStorage, but that id is a
// memory of a SERVER row. When the row goes — a teammate deletes the project,
// the user leaves the team, a restore rolls the database back — the app keeps
// asking for it and every project-scoped screen 404s, with no way back because
// the whole shell reads `useWorkspaceStore.project` directly.
//
// Clearing it drops the shell to Home, where the project list is authoritative
// and the user can open or create a real one.
import { useEffect, useRef } from 'react'
import { getProject } from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

export function useValidateProject(): void {
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated')
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  // One check per project id: this is a correction for a rare, permanent state,
  // not a liveness poll.
  const checked = useRef<string | null>(null)

  useEffect(() => {
    // A 404 while signed out proves nothing about the project — only that we
    // were not allowed to ask.
    if (!isAuthenticated || !projectId || checked.current === projectId) return
    checked.current = projectId

    let cancelled = false
    getProject(projectId).catch((error: unknown) => {
      // ONLY a 404 means "gone". A 401, a 5xx or an unreachable API means we
      // could not ask — discarding a good project reference over a blip would
      // be the same error as reporting a rejected token as "backend offline".
      // That rule now lives in one place (lib/api/errors.ts) because the team
      // half of it was missing and cost a user hours.
      if (cancelled || classifyFetchError(error) !== 'gone') return
      // Re-read: the user may have switched projects while this was in flight.
      if (useWorkspaceStore.getState().project?.id !== projectId) return
      useWorkspaceStore.getState().setProject(null)
    })
    return () => {
      cancelled = true
    }
  }, [isAuthenticated, projectId])
}
