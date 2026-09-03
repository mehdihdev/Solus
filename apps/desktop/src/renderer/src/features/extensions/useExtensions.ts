// SOLUSDEV-235 — the Store's data hook: catalog × per-project install state ×
// the project's connected sources → one `ExtensionView` per extension.
//
// THIS IS THE BACKEND SEAM. Today the catalog is in-repo and install state is
// local; when the Store API lands, this hook swaps its inputs (fetch the
// catalog, read/write installs server-side) and every Store surface keeps
// rendering the same `ExtensionView`.
import { useMemo } from 'react'
import type { ExtensionView, RunFrequency } from './extension.types'
import { EXTENSION_CATALOG, findExtension } from './extensions.catalog'
import { buildView, connectedKinds } from './extensionLogic'
import { selectInstallState, useExtensionsStore } from './extensionsStore'
import { useProjectSources, type ProjectSourcesStatus } from '../project/useProjectSources'
import { useWorkspaceStore } from '../../store/workspaceStore'

export interface ExtensionActions {
  install: (extensionId: string) => void
  uninstall: (extensionId: string) => void
  setEnabled: (extensionId: string, enabled: boolean) => void
  setRunFrequency: (extensionId: string, freq: RunFrequency) => void
}

export interface ExtensionsData {
  projectId: string
  views: ExtensionView[]
  /** `offline` means requirements were evaluated against no sources — say so. */
  sourcesStatus: ProjectSourcesStatus
  actions: ExtensionActions
}

export function useExtensions(projectId: string): ExtensionsData {
  const sources = useProjectSources()
  // `useProjectSources` reads the OPEN project; if a caller scopes this hook to
  // another project, its requirements must not be judged against foreign sources.
  const openProjectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const scoped = openProjectId === projectId
  const sourcesStatus: ProjectSourcesStatus = scoped ? sources.status : 'offline'
  const byProject = useExtensionsStore((s) => s.byProject)
  const sourceList = sources.sources

  const views = useMemo(() => {
    const connected = connectedKinds(scoped ? sourceList.map((s) => s.type) : [])
    return EXTENSION_CATALOG.map((m) =>
      buildView(m, selectInstallState(byProject, projectId, m), connected)
    )
  }, [byProject, projectId, scoped, sourceList])

  const actions = useMemo<ExtensionActions>(() => {
    const store = useExtensionsStore.getState
    return {
      install: (id) => {
        const m = findExtension(id)
        if (m) store().install(projectId, m)
      },
      uninstall: (id) => {
        const m = findExtension(id)
        if (m) store().uninstall(projectId, m)
      },
      setEnabled: (id, enabled) => {
        const m = findExtension(id)
        if (m) store().setEnabled(projectId, m, enabled)
      },
      setRunFrequency: (id, freq) => {
        const m = findExtension(id)
        if (m) store().setRunFrequency(projectId, m, freq)
      }
    }
  }, [projectId])

  return { projectId, views, sourcesStatus, actions }
}
