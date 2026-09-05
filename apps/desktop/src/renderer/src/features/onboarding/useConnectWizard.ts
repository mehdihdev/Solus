// Surface glue for the connect wizard (SOLUSDEV-165), shared by the Sources
// page and onboarding: tracks which catalog entry the wizard is open for,
// starts the right real flow (OAuth bridge / committed-export), and implements
// the cancel contract — closing mid-flight forgets the attempt immediately
// (the flow's own progress is suppressed and the browser handshake aborted).
//
// Cancel NEVER deletes anything. For multi-selection connectors the backend
// REUSES the existing connected source, so `result.sourceId` can name a live,
// populated source — deleting it here would destroy real graph data on a
// stray backdrop click (CLAUDE.md §7: destructive actions need explicit
// confirmation). A genuinely half-configured source stays visible on the
// Sources page, where the confirmed Disconnect already lives. And a flow that
// completed successfully despite the cancel keeps its source and is reported —
// finished work is never silently discarded.
import { useRef, useState } from 'react'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import type { Connection } from '../../lib/api/resources'
import { linkedAccountFor } from '../workspace/useAccountConnections'
import type { WizardScope } from './connectSteps'
import { EMPTY_EXPORT_ERROR, MAX_EXPORT_BYTES, OVERSIZE_EXPORT_ERROR } from './edaConnect'
import type { CatalogEntry } from './integrationCatalog'
import { noBridgeError } from './oauthConnect'
import { useOnboardingStore } from './onboardingStore'
import { useEdaConnect } from './useEdaConnect'
import { connectOptions, useOAuthConnect } from './useOAuthConnect'

export const NOT_LINKED_ERROR = 'Solus API unreachable — retry once you are back online.'

/** One begin/pickFile invocation for one entry. Latches are PER ATTEMPT so a
 * late-settling abandoned flow is never governed by a newer attempt's cancel. */
interface Attempt {
  cancelled: boolean
  settled: boolean
}

export interface UseConnectWizardOptions {
  /** The project sources attach to; null when no linked project exists yet. */
  projectId: string | null
  /** Called once a connect settles successfully (refresh lists, recount, …). */
  onConnected?: () => void
  /** SOLUSDEV-241: `account` binds a provider account with no project (Home).
   *  Default `project`. */
  scope?: WizardScope
  /** SOLUSDEV-241: the user's linked accounts. A CONNECTED one for the
   *  entry's provider is reused — no second sign-in. */
  linkedConnections?: readonly Connection[]
}

export interface UseConnectWizard {
  /** The entry the wizard is open for, or null when it is closed. */
  active: CatalogEntry | null
  /** The linked account the active entry will reuse, if any (SOLUSDEV-241). */
  linkedAccount: Connection | null
  open: (entry: CatalogEntry) => void
  /** Start (or retry) the flow for the active entry — OAuth path. */
  begin: () => Promise<void>
  /** Start the flow with the user's picked export file — validated by size
   * BEFORE it is read into memory. */
  pickFile: (file: File) => Promise<void>
  /** Close the wizard. Mid-flight this cancels the attempt. */
  close: () => void
  select: ReturnType<typeof useOAuthConnect>['select']
  submitConfig: ReturnType<typeof useOAuthConnect>['submitConfig']
  chooseAccess: ReturnType<typeof useOAuthConnect>['chooseAccess']
}

export function useConnectWizard(options: UseConnectWizardOptions): UseConnectWizard {
  const { projectId, onConnected, scope = 'project', linkedConnections = [] } = options
  const [active, setActive] = useState<CatalogEntry | null>(null)
  const linkedAccount =
    active && scope === 'project' ? linkedAccountFor(linkedConnections, active.id) : null
  const oauth = useOAuthConnect()
  const eda = useEdaConnect()
  /** The latest attempt per entry id. */
  const attempts = useRef<Record<string, Attempt>>({})

  const beginAttempt = (entry: CatalogEntry): Attempt => {
    const attempt: Attempt = { cancelled: false, settled: false }
    attempts.current[entry.id] = attempt
    return attempt
  }

  /** One settlement path for both engines, keyed to ITS OWN attempt. */
  const settle = (entry: CatalogEntry, attempt: Attempt, result: { ok: boolean }): void => {
    attempt.settled = true
    if (result.ok) {
      // Success is reported even after a cancel: the work is real, the source
      // exists, and hiding it would be dishonest. The list refresh surfaces it.
      onConnected?.()
      return
    }
    // A cancelled failure ends quiet: progress was suppressed and the state
    // cleared at close(). Sweep once more in case a write predated the latch —
    // but only when no newer attempt owns this entry's tile.
    if (attempt.cancelled && attempts.current[entry.id] === attempt) {
      useOnboardingStore.getState().clearConnection(entry.id)
    }
  }

  const guard = (entry: CatalogEntry): boolean => {
    const { failConnect } = useOnboardingStore.getState()
    if (scope === 'project' && !projectId) {
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
    const attempt = beginAttempt(entry)
    if (scope === 'account') {
      const bound = await oauth.startAccount(entry.id, connectOptions(entry))
      settle(entry, attempt, bound)
      return
    }
    const linked = linkedAccountFor(linkedConnections, entry.id)
    const result = await oauth.start(projectId!, entry.id, {
      ...connectOptions(entry),
      linkedConnection: linked ? { id: linked.id, login: linked.account_login } : null
    })
    settle(entry, attempt, result)
  }

  const pickFile = async (file: File): Promise<void> => {
    const entry = active
    if (!entry || !guard(entry)) return
    // Bound by size BEFORE file.text() — reading a multi-GB pick into a string
    // would hang the renderer long before the engine's own validation runs.
    const { failConnect } = useOnboardingStore.getState()
    if (file.size === 0) {
      failConnect(entry.id, EMPTY_EXPORT_ERROR)
      return
    }
    if (file.size > MAX_EXPORT_BYTES) {
      failConnect(entry.id, OVERSIZE_EXPORT_ERROR)
      return
    }
    const attempt = beginAttempt(entry)
    const content = await file.text()
    // The wizard may have closed during the read — a cancelled attempt must
    // not go on to create and sync a source.
    if (attempt.cancelled) return
    const result = await eda.start(projectId!, entry.id, { fileName: file.name, content })
    settle(entry, attempt, result)
  }

  const close = (): void => {
    const entry = active
    setActive(null)
    if (!entry) return
    const attempt = attempts.current[entry.id]
    // Settled (done, error, or never started): keep the tile state — an error
    // stays retryable, a done stays done. Only an in-flight attempt cancels.
    if (!attempt || attempt.settled) return
    attempt.cancelled = true
    // Unblock any waiting input step / abort the browser handshake so the
    // flow settles, and suppress the owning engine's further progress writes.
    if (entry.mode === 'oauth') oauth.cancel()
    else eda.cancel()
    useOnboardingStore.getState().clearConnection(entry.id)
  }

  return {
    active,
    linkedAccount,
    open: setActive,
    begin,
    pickFile,
    close,
    select: oauth.select,
    submitConfig: oauth.submitConfig,
    chooseAccess: oauth.chooseAccess
  }
}
