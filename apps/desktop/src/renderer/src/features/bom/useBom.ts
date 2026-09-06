// SOLUSDEV-246 / STORE ST4 — the BOM page's data hook. THIS IS THE BACKEND
// SEAM: the screen renders `BomViewApi` and calls `BomActions`; everything
// behind them is here. Degrades like the other workspace hooks: `not_installed`
// when the bundle's routes answer 404 (not installed / disabled / blocked in
// this project), `offline` when nothing could be read at all — never a stale or
// invented list. A failed refresh keeps the rows already on screen.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import {
  createBomRow,
  deleteBomRow,
  fetchBomCsv,
  getBomView,
  patchBomRow,
  type BomItemInput,
  type BomLifecycleState,
  type BomRowPatch,
  type BomViewApi
} from '../../lib/api/resources.bom'
import { useInterval } from '../../lib/useInterval'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

/** Same cadence as the other project surfaces: another member's edit lands without a click. */
export const BOM_POLL_MS = 10_000

export type BomStatus = 'loading' | 'ready' | 'not_installed' | 'offline'

export type BomOutcome = { readonly ok: true } | { readonly ok: false; readonly message: string }

export interface BomActions {
  addRow: (input: BomItemInput) => Promise<BomOutcome>
  patchRow: (key: string, patch: BomRowPatch) => Promise<BomOutcome>
  setState: (key: string, state: BomLifecycleState) => Promise<BomOutcome>
  removeRow: (key: string) => Promise<BomOutcome>
  exportCsv: (filename: string) => Promise<BomOutcome>
  refresh: () => Promise<void>
}

export interface BomData {
  readonly status: BomStatus
  readonly view: BomViewApi | null
  readonly actions: BomActions
}

export interface BomDeps {
  /** Hand the CSV bytes to the platform (a download in Electron). */
  readonly save?: (filename: string, text: string) => void
}

/** Default saver: a blob download, which Electron routes to the OS save dialog. */
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function failure(error: unknown): BomOutcome {
  const message =
    error instanceof ApiError ? error.message : "Couldn't reach Solus. Try again in a moment."
  return { ok: false, message }
}

export function useBom(projectId: string, deps: BomDeps = {}): BomData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [remote, setStatus] = useState<BomStatus>('loading')
  const [view, setView] = useState<BomViewApi | null>(null)
  const status: BomStatus = fetchEnabled ? remote : 'offline'
  const save = deps.save ?? downloadText

  // Settles in the promise's callbacks (never synchronously in an effect), like
  // the rail's listing: the state lands when the server answers.
  const load = useCallback((): Promise<void> => {
    if (!fetchEnabled) return Promise.resolve()
    return getBomView(projectId).then(
      (next) => {
        setView(next)
        setStatus('ready')
      },
      (error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          setView(null)
          setStatus('not_installed')
          return
        }
        // A blip must not blank rows already on screen.
        setView((previous) => {
          setStatus(previous ? 'ready' : 'offline')
          return previous
        })
      }
    )
  }, [fetchEnabled, projectId])

  useEffect(() => {
    void load()
  }, [load])
  useInterval(() => void load(), BOM_POLL_MS, fetchEnabled && status === 'ready')

  const actions = useMemo<BomActions>(() => {
    const write = async (op: () => Promise<unknown>): Promise<BomOutcome> => {
      try {
        await op()
      } catch (error) {
        return failure(error)
      }
      await load()
      return { ok: true }
    }
    return {
      addRow: (input) => write(() => createBomRow(projectId, input)),
      patchRow: (key, patch) => write(() => patchBomRow(projectId, key, patch)),
      setState: (key, state) => write(() => patchBomRow(projectId, key, { state })),
      removeRow: (key) => write(() => deleteBomRow(projectId, key)),
      exportCsv: async (filename) => {
        try {
          save(filename, await fetchBomCsv(projectId))
          return { ok: true }
        } catch (error) {
          return failure(error)
        }
      },
      refresh: load
    }
  }, [load, projectId, save])

  return { status, view, actions }
}
