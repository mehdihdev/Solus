// Real committed-export EDA connect orchestration (SOLUSDEV-100, multi-file in
// SOLUSDEV-252). The EDA sibling of githubConnect.ts: no OAuth — the user picks
// a netlist export and/or a board file, we create the source with the file
// CONTENT as config.export / config.board (what the backend EdaExportConnector
// reads), trigger a sync, and poll it to completion. Transport is injected so
// this is unit-testable without React.
import type { Source, Sync } from '../../lib/api/resources'
import { NO_FILES_ERROR, type EdaExportFile, type EdaExportFiles } from './kicadFiles'
import type { ConnectionState } from './onboardingStore'
import {
  isSettledJob,
  jobFailure,
  pollAcceptedSync,
  STILL_INDEXING_RESULT,
  indexedSyncDetail,
  type SyncJobApi,
  type SyncPollApi
} from './sourceSync'

export type { EdaExportFile, EdaExportFiles } from './kicadFiles'

/** The slice of the typed API surface this orchestration depends on. */
export interface EdaConnectApi extends SyncPollApi, SyncJobApi {
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
/** A `file.text()` rejection (permissions, file moved, media gone). The raw
 * error never reaches the UI. */
export const FILE_READ_ERROR = 'Could not read the selected file. Try choosing it again.'

function busy(label: string, sourceId?: string): ConnectionState {
  // Everything after the file pick is indexing work from the wizard's view.
  return { phase: 'busy', stage: 'index', label, sourceId }
}

/** "power-board.xml" → "power-board"; falls back to the provider id. */
function sourceNameFrom(fileName: string, provider: string): string {
  const base = fileName.replace(/\.[^.]+$/, '').trim()
  return base || provider
}

/** The picked files in a stable order: netlist first, then board. */
function presentFiles(files: EdaExportFiles): EdaExportFile[] {
  return [files.netlist, files.board].filter((file): file is EdaExportFile => file !== undefined)
}

/** The source config: only the keys that were picked — the API schema expects
 * strings where a key is present, never null/undefined. */
function exportConfig(files: EdaExportFiles): Record<string, string> {
  return {
    ...(files.netlist ? { export: files.netlist.content } : {}),
    ...(files.board ? { board: files.board.content } : {})
  }
}

/** "netlist" / "board" / "netlist and board" for the progress label. */
function describeInputs(files: EdaExportFiles): string {
  if (files.netlist && files.board) return 'netlist and board'
  return files.board ? 'board' : 'netlist'
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
  files: EdaExportFiles
): Promise<EdaConnectResult> {
  const picked = presentFiles(files)
  const invalid = validateExports(picked)
  if (invalid) {
    deps.onProgress({ phase: 'error', error: invalid })
    return { ok: false, error: invalid }
  }

  try {
    deps.onProgress(busy(`Reading ${picked.map((file) => file.fileName).join(', ')}…`))
    const source = await deps.api.createSource(projectId, {
      type: provider,
      name: sourceNameFrom(picked[0].fileName, provider),
      config: exportConfig(files)
    })

    deps.onProgress(busy(`Parsing ${describeInputs(files)} & building the graph…`, source.id))
    const accepted = await deps.api.triggerSync(projectId, source.id)

    const job = await pollAcceptedSync(deps.api, projectId, accepted.job_id, deps.sleep)
    if (job && !isSettledJob(job)) {
      deps.onProgress({ phase: 'done', sourceId: source.id, result: STILL_INDEXING_RESULT })
      return { ok: true, sourceId: source.id, result: STILL_INDEXING_RESULT }
    }
    const error = jobFailure(job)
    if (error) {
      deps.onProgress({ phase: 'error', error, sourceId: source.id })
      return { ok: false, error, sourceId: source.id }
    }

    const synced = await deps.api.getSource(projectId, source.id)
    const detail = await indexedSyncDetail(deps.api, projectId, source.id, synced.entity_count)
    const result = `Connected — ${detail}`
    deps.onProgress({ phase: 'done', sourceId: source.id, result })
    return { ok: true, sourceId: source.id, result }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Connect failed.'
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}

/** At least one file, and every present file non-empty and within the bound. */
function validateExports(files: readonly EdaExportFile[]): string | null {
  if (files.length === 0) return NO_FILES_ERROR
  for (const file of files) {
    if (!file.content.trim()) return EMPTY_EXPORT_ERROR
    if (new TextEncoder().encode(file.content).length > MAX_EXPORT_BYTES) {
      return OVERSIZE_EXPORT_ERROR
    }
  }
  return null
}
