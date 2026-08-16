// Surface glue for the connect wizard (SOLUSDEV-165), shared by the Sources
// page and onboarding: tracks which catalog entry the wizard is open for,
// starts the right real flow (OAuth bridge / committed-export), and implements
// the cancel contract — closing mid-flight forgets the attempt immediately and,
// once the abandoned flow settles, deletes the dangling half-configured source
// (retain_entities=false: it produced no graph data). A flow that completed
// successfully despite the cancel keeps its source; finished work is reported,
// never silently discarded.
import { useRef, useState } from 'react'
import { disconnectSource } from '../../lib/api/resources'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import type { EdaExportFile } from './edaConnect'
import type { CatalogEntry } from './integrationCatalog'
import { noBridgeError } from './oauthConnect'
import { useOnboardingStore } from './onboardingStore'
import { useEdaConnect } from './useEdaConnect'
import { connectOptions, useOAuthConnect } from './useOAuthConnect'

export const NOT_LINKED_ERROR = 'Solus API unreachable — retry once you are back online.'

/** What both flow engines resolve with, as far as cleanup is concerned. */
interface SettledResult {
  ok: boolean
  sourceId?: string
}

export interface UseConnectWizardOptions {
  /** The project sources attach to; null when no linked project exists yet. */
  projectId: string | null
  /** Called once a connect settles successfully (refresh lists, recount, …). */
  onConnected?: () => void
}

export interface UseConnectWizard {
  /** The entry the wizard is open for, or null when it is closed. */
  active: CatalogEntry | null
  open: (entry: CatalogEntry) => void
  /** Start (or retry) the flow for the active entry — OAuth path. */
  begin: () => Promise<void>
  /** Start the flow with the picked committed export — file path. */
  pickFile: (file: EdaExportFile) => Promise<void>
  /** Close the wizard. Mid-flight this cancels the attempt. */
  close: () => void
  select: ReturnType<typeof useOAuthConnect>['select']
  submitConfig: ReturnType<typeof useOAuthConnect>['submitConfig']
  chooseAccess: ReturnType<typeof useOAuthConnect>['chooseAccess']
}

export function useConnectWizard(options: UseConnectWizardOptions): UseConnectWizard {
  const { projectId, onConnected } = options
  const [active, setActive] = useState<CatalogEntry | null>(null)
  const oauth = useOAuthConnect()
  const eda = useEdaConnect()
  // Latched by close() while a flow is in flight; cleared on the next start.
  const cancelled = useRef(false)

  /** One settlement path for both engines: cleanup after a cancel, report
   * success otherwise. Runs strictly after the flow's final progress write. */
  const settle = (entry: CatalogEntry, result: SettledResult): void => {
    if (!cancelled.current) {
      if (result.ok) onConnected?.()
      return
    }
    if (result.ok) {
      // The user closed the wizard but the connect finished anyway: keep the
      // source and its 'done' state — deleting finished work on a stale cancel
      // would be destructive, not tidy.
      onConnected?.()
      return
    }
    if (result.sourceId && projectId) {
      // Best-effort: a failed cleanup only leaves a disconnected-looking
      // source the user can remove from the Sources list.
      void disconnectSource(projectId, result.sourceId, { retainEntities: false }).catch(
        () => undefined
      )
    }
    useOnboardingStore.getState().clearConnection(entry.id)
  }

  const guard = (entry: CatalogEntry): boolean => {
    const { failConnect } = useOnboardingStore.getState()
    if (!projectId) {
      failConnect(entry.id, NOT_LINKED_ERROR)
      return false
    }
    if (entry.mode === 'oauth' && !getDesktopOAuthBridge()) {
      failConnect(entry.id, noBridgeError(entry.name))
      return false
    }
    return true
  }

  const begin = async (): Promise<void> => {
    const entry = active
    if (!entry || !guard(entry)) return
    cancelled.current = false
    const result = await oauth.start(projectId!, entry.id, connectOptions(entry))
    settle(entry, result)
  }

  const pickFile = async (file: EdaExportFile): Promise<void> => {
    const entry = active
    if (!entry || !guard(entry)) return
    cancelled.current = false
    const result = await eda.start(projectId!, entry.id, file)
    settle(entry, result)
  }

  const close = (): void => {
    const entry = active
    setActive(null)
    if (!entry) return
    const state = useOnboardingStore.getState().connections[entry.id]
    if (state?.phase !== 'busy') return
    // Cancel the in-flight attempt: unblock any waiting input step so the flow
    // settles, and forget the tile state right away. settle() finishes the job.
    cancelled.current = true
    oauth.cancel()
    useOnboardingStore.getState().clearConnection(entry.id)
  }

  return {
    active,
    open: setActive,
    begin,
    pickFile,
    close,
    select: oauth.select,
    submitConfig: oauth.submitConfig,
    chooseAccess: oauth.chooseAccess
  }
}
