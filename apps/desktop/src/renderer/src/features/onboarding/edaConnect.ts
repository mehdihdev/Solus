// Real committed-export EDA connect orchestration (SOLUSDEV-100). The EDA
// sibling of githubConnect.ts: no OAuth — the user picks the committed netlist
// export, we create the source with the file CONTENT as config.export (the v1
// scaffold the backend EdaExportConnector reads), trigger a sync, and poll it
// to completion. Transport is injected so this is unit-testable without React.
import type { Source, Sync } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'
import { pollSync, syncErrorMessage, type SyncPollApi } from './sourceSync'

/** The slice of the typed API surface this orchestration depends on. */
export interface EdaConnectApi extends SyncPollApi {
  createSource: (
    projectId: string,
    input: { type: string; name: string; config?: Record<string, unknown> }
  ) => Promise<Source>
  triggerSync: (projectId: string, sourceId: string) => Promise<{ job_id: string; status: string }>
  getSyncs: (projectId: string, sourceId: string) => Promise<Sync[]>
  getSource: (projectId: string, sourceId: string) => Promise<Source>
}

export interface EdaConnectDeps {
  api: EdaConnectApi
  /** Push live connection state into the store. */
  onProgress: (state: ConnectionState) => void
  /** Optional sleep override so tests don't actually wait between poll ticks. */
  sleep?: (ms: number) => Promise<void>
}

/** The user-picked committed export, already read into memory. */
export interface EdaExportFile {
  fileName: string
  content: string
}

export interface EdaConnectResult {
  ok: boolean
  sourceId?: string
  result?: string
  error?: string
}

/** Mirrors the backend bound (eda.MAX_EXPORT_BYTES) so an oversized file fails
 * fast with a friendly message instead of a rejected upload. */
export const MAX_EXPORT_BYTES = 8 * 1024 * 1024

export const EMPTY_EXPORT_ERROR = 'The selected file is empty.'
export const OVERSIZE_EXPORT_ERROR = 'The selected file is too large (limit 8 MB).'

function busy(label: string, sourceId?: string): ConnectionState {
  // Everything after the file pick is indexing work from the wizard's view.
  return { phase: 'busy', stage: 'index', label, sourceId }
}

/** "power-board.xml" → "power-board"; falls back to the provider id. */
function sourceNameFrom(fileName: string, provider: string): string {
  const base = fileName.replace(/\.[^.]+$/, '').trim()
  return base || provider
}

/**
 * Drive the full committed-export connect. Reports progress through
 * `onProgress`; returns a structured result. Never throws — failures resolve
 * to `{ ok: false, error }` so the caller can mark the tile errored.
 */
export async function runEdaConnect(
  deps: EdaConnectDeps,
  projectId: string,
  provider: string,
  file: EdaExportFile
): Promise<EdaConnectResult> {
  const invalid = validateExport(file)
  if (invalid) {
    deps.onProgress({ phase: 'error', error: invalid })
    return { ok: false, error: invalid }
  }

  try {
    deps.onProgress(busy(`Reading ${file.fileName}…`))
    const source = await deps.api.createSource(projectId, {
      type: provider,
      name: sourceNameFrom(file.fileName, provider),
      config: { export: file.content }
    })

    deps.onProgress(busy('Parsing netlist & building the graph…', source.id))
    await deps.api.triggerSync(projectId, source.id)

    const sync = await pollSync(deps.api, projectId, source.id, deps.sleep)
    if (!sync) {
      const error = 'Sync timed out.'
      deps.onProgress({ phase: 'error', error, sourceId: source.id })
      return { ok: false, error, sourceId: source.id }
    }
    if (sync.status === 'failed') {
      const error = syncErrorMessage(sync)
      deps.onProgress({ phase: 'error', error, sourceId: source.id })
      return { ok: false, error, sourceId: source.id }
    }

    const synced = await deps.api.getSource(projectId, source.id)
    const count = synced.entity_count ?? sync.entities_created
    const result = `Connected — ${count} entities indexed`
    deps.onProgress({ phase: 'done', sourceId: source.id, result })
    return { ok: true, sourceId: source.id, result }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Connect failed.'
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}

function validateExport(file: EdaExportFile): string | null {
  if (!file.content.trim()) {
    return EMPTY_EXPORT_ERROR
  }
  if (new TextEncoder().encode(file.content).length > MAX_EXPORT_BYTES) {
    return OVERSIZE_EXPORT_ERROR
  }
  return null
}
