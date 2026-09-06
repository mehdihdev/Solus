import { useMemo, useSyncExternalStore } from 'react'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'
import { apiBaseUrl, createApiClient, type ApiClient } from '../../lib/api/client'
import {
  listAllSources,
  type Source,
  type Connection,
  type SelectableItem
} from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import {
  attachServiceDocument,
  waitForServiceJob,
  type ServiceSelection
} from './serviceAttachments'

export type SelectService = (selection: ServiceSelection, documentId: string) => void
interface ProjectView {
  sources: Source[] | null
  busyId: string | null
  error: string | null
}
class ServiceProject {
  private state: ProjectView = { sources: null, busyId: null, error: null }
  private listeners = new Set<() => void>()
  private pending: Promise<void> | null = null
  private failedImports = new Map<string, string>()
  constructor(
    private projectId: string,
    private client: ApiClient,
    private assertCurrent: () => void,
    private onSelected: SelectService
  ) {}
  snapshot = (): ProjectView => this.state
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  private publish(update: Partial<ProjectView>): void {
    this.assertCurrent()
    this.state = { ...this.state, ...update }
    this.listeners.forEach((listener) => listener())
  }
  load = (): Promise<void> => {
    if (this.pending) return this.pending
    if (this.state.sources) return Promise.resolve()
    this.assertCurrent()
    this.pending = listAllSources(this.projectId, this.client)
      .then((sources) => this.publish({ sources, error: null }))
      .catch((error: unknown) => this.report(error))
      .finally(() => {
        this.pending = null
      })
    return this.pending
  }
  private report(error: unknown): void {
    try {
      this.publish({
        error: error instanceof Error ? error.message : 'Could not add the document.',
        busyId: null
      })
    } catch {
      /* A different workspace cannot receive this operation's result. */
    }
  }
  select = async (connection: Connection, item: SelectableItem): Promise<void> => {
    if (this.state.busyId) return
    const key = `${connection.id}:${item.id}`
    try {
      const failed = this.failedImports.get(key)
      if (failed) throw new Error(failed)
      this.publish({ busyId: key, error: null })
      await this.load()
      this.assertCurrent()
      if (!this.state.sources)
        throw new Error(this.state.error ?? 'Could not read project sources.')
      const selection = await attachServiceDocument({
        projectId: this.projectId,
        connection,
        item,
        sources: this.state.sources,
        client: this.client,
        assertCurrent: this.assertCurrent
      })
      const sources = this.state.sources.filter((source) => source.id !== selection.source.id)
      this.publish({ sources: [...sources, selection.source] })
      await this.observe(selection, key)
      this.assertCurrent()
      this.onSelected(selection, item.id)
      this.publish({ busyId: null })
    } catch (error) {
      this.report(error)
    }
  }
  private async observe(selection: ServiceSelection, key: string): Promise<void> {
    if (!selection.jobId) return
    try {
      await waitForServiceJob({
        projectId: this.projectId,
        jobId: selection.jobId,
        client: this.client,
        assertCurrent: this.assertCurrent
      })
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'Import could not finish.'
      const message = `${reason} Open Sources to check the import, then return to Workspace.`
      this.failedImports.set(key, message)
      throw new Error(message)
    }
  }
}
export function isServiceAdded(
  sources: readonly Source[] | null,
  connection: Connection,
  item: SelectableItem
): boolean {
  return (
    sources?.some(
      (source) =>
        source.connection_id === connection.id &&
        source.type === connection.provider &&
        (connection.provider === 'onshape'
          ? Array.isArray(source.config.documents) && source.config.documents.includes(item.id)
          : source.config.repo === item.config?.repo &&
            source.config.branch === item.config?.branch)
    ) ?? false
  )
}
export function useServiceAttachments(
  projectId: string | null,
  onSelected: SelectService
): { session: ServiceProject; state: ProjectView } {
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const generation = useWorkspaceSessionGeneration()
  const session = useMemo(() => {
    const assertCurrent = (): void => {
      const auth = useAuthStore.getState()
      if (
        workspaceSessionGeneration() !== generation ||
        !projectId ||
        useWorkspaceStore.getState().project?.id !== projectId ||
        `${auth.status}:${auth.user?.email ?? ''}` !== identity
      )
        throw new Error('The workspace session has changed.')
    }
    const client = createApiClient({
      baseUrl: apiBaseUrl,
      getToken: () => {
        assertCurrent()
        return useAuthStore.getState().accessToken
      }
    })
    return new ServiceProject(projectId ?? '', client, assertCurrent, onSelected)
  }, [projectId, identity, onSelected, generation])
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
  return { session, state }
}
