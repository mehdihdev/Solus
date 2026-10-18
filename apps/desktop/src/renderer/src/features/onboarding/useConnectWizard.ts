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
// Home's connected-accounts card, where the confirmed Disconnect already lives. And a flow that
// completed successfully despite the cancel keeps its source and is reported —
// finished work is never silently discarded.
import { useEffect, useMemo, useRef, useState } from 'react'
import { create } from 'zustand'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { listSelectable, type Connection, type SelectableItem } from '../../lib/api/resources'
import { getTeamInstallation, listTeamGithubRepos } from '../../lib/api/resources.teamGithub'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { teamRepoSections, type PickerSection } from './teamRepoSection'
import { linkedAccountFor } from '../workspace/useAccountConnections'
import type { WizardScope } from './connectSteps'
import {
  EMPTY_EXPORT_ERROR,
  FILE_READ_ERROR,
  MAX_EXPORT_BYTES,
  OVERSIZE_EXPORT_ERROR
} from './edaConnect'
import type { CatalogEntry } from './integrationCatalog'
import {
  assembleExportInputs,
  maxPickedFiles,
  NO_FILES_ERROR,
  tooManyFilesError,
  type EdaExportFile,
  type ExportAssembly
} from './kicadFiles'
import { noBridgeError } from './oauthConnect'
import { useOnboardingStore } from './onboardingStore'
import { useEdaConnect } from './useEdaConnect'
import { connectOptions, useOAuthConnect } from './useOAuthConnect'

export const NOT_LINKED_ERROR = 'Solus API unreachable — retry once you are back online.'

/** The team repo the user just clicked in the picker, staged for the next
 *  `begin()` (SOLUSDEV-216). The modal's props are fixed by its callers, so the
 *  pick travels through this one-slot store instead of a new prop: begin()
 *  takes it exactly once, close() forgets it. */
export const useTeamPick = create<{ picked: SelectableItem | null }>(() => ({ picked: null }))

const takeTeamPick = (): SelectableItem | null => {
  const { picked } = useTeamPick.getState()
  if (picked) useTeamPick.setState({ picked: null })
  return picked
}

/** The installation's first page of repos; none for a suspended installation. */
async function loadTeamGithub(teamId: string) {
  const installation = await getTeamInstallation(teamId)
  const repos = installation?.status === 'active' ? (await listTeamGithubRepos(teamId)).items : []
  return { installation, repos }
}

/**
 * SOLUSDEV-216: the GitHub picker's team section, for a project whose team has
 * an installation. null for every other provider/scope, for a team with no
 * installation, and when the lookup fails — each of which is the legacy wizard.
 */
export function useTeamPicker(
  entry: Pick<CatalogEntry, 'id'>,
  scope: WizardScope,
  linkedLogin: string | null
): readonly PickerSection[] | null {
  const teamId = useWorkspaceStore((s) => s.project?.teamId ?? s.teamId)
  const enabled = scope === 'project' && entry.id === 'github' && !!teamId
  const [data, setData] = useState<Awaited<ReturnType<typeof loadTeamGithub>> | null>(null)
  useEffect(() => {
    if (!enabled || !teamId) return
    let live = true
    loadTeamGithub(teamId).then(
      (loaded) => live && setData(loaded),
      () => live && setData(null)
    )
    return () => {
      live = false
      setData(null)
    }
  }, [enabled, teamId])
  return useMemo(
    () => (enabled && data ? teamRepoSections({ ...data, linkedLogin }) : null),
    [enabled, data, linkedLogin]
  )
}

/** One begin/pickFiles invocation for one entry. Latches are PER ATTEMPT so a
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
  /** Start the flow with the user's picked export files (a netlist and/or a
   * board) — the pick is bounded by COUNT and every file by SIZE before any is
   * read into memory, then each is routed by CONTENT to its config key. */
  pickFiles: (files: File[]) => Promise<void>
  /** Close the wizard. Mid-flight this cancels the attempt. */
  close: () => void
  refreshSelection: () => Promise<SelectableItem[]>
  select: ReturnType<typeof useOAuthConnect>['select']
  submitConfig: ReturnType<typeof useOAuthConnect>['submitConfig']
  chooseAccess: ReturnType<typeof useOAuthConnect>['chooseAccess']
}

/** The size-only pre-read check for one picked file, or null when it may be read. */
function fileSizeError(file: File): string | null {
  if (file.size === 0) return EMPTY_EXPORT_ERROR
  if (file.size > MAX_EXPORT_BYTES) return OVERSIZE_EXPORT_ERROR
  return null
}

/** Every refusal decidable WITHOUT reading a byte: nothing picked, too many
 * files for the provider, or a file outside the size bound. Count comes first
 * so a folder of 200 files is refused in O(1) memory. */
function prePickError(providerId: string, files: readonly File[]): string | null {
  if (files.length === 0) return NO_FILES_ERROR
  if (files.length > maxPickedFiles(providerId)) return tooManyFilesError(providerId)
  return files.map(fileSizeError).find((error): error is string => error !== null) ?? null
}

/** Read every picked file, or null when ANY read rejects (permissions, file
 * moved, media gone) — the caller decides how to report it. */
async function readExportFiles(files: readonly File[]): Promise<EdaExportFile[] | null> {
  try {
    return await Promise.all(
      files.map(async (file) => ({ fileName: file.name, content: await file.text() }))
    )
  } catch {
    return null
  }
}

function useWizardAttempt(options: UseConnectWizardOptions) {
  const { projectId, onConnected, scope = 'project', linkedConnections = [] } = options
  const [active, setActive] = useState<CatalogEntry | null>(null)
  const linkedAccount =
    active && scope === 'project' ? linkedAccountFor(linkedConnections, active.id) : null
  const oauth = useOAuthConnect()
  const eda = useEdaConnect()
  /** The latest attempt per entry id. */
  const attempts = useRef<Record<string, Attempt>>({})

  // Home can switch account → project scope in the same event that opens the
  // wizard. Use the committed context; a previous sign-in failure is no longer
  // the current project-selection attempt after an account becomes available.
  const linkedAccountId = linkedAccount?.id
  useEffect(() => {
    if (!active || !linkedAccountId) return
    const attempt = attempts.current[active.id]
    if (attempt && !attempt.settled) return
    const store = useOnboardingStore.getState()
    if (store.connections[active.id]?.phase === 'error') store.clearConnection(active.id)
  }, [active, linkedAccountId])

  const beginAttempt = (entry: CatalogEntry): Attempt => {
    const attempt: Attempt = { cancelled: false, settled: false }
    attempts.current[entry.id] = attempt
    return attempt
  }

  const settle = settleWizardAttempt(attempts, onConnected)

  const { guard, refreshSelection } = wizardAvailability(
    active,
    scope,
    projectId,
    linkedConnections
  )

  const close = (): void => {
    const entry = active
    setActive(null)
    useTeamPick.setState({ picked: null })
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
    setActive,
    oauth,
    eda,
    projectId,
    scope,
    linkedConnections,
    guard,
    beginAttempt,
    settle,
    close,
    refreshSelection
  }
}

export function useConnectWizard(options: UseConnectWizardOptions): UseConnectWizard {
  const context = useWizardAttempt(options)
  return {
    active: context.active,
    linkedAccount: context.linkedAccount,
    open: context.setActive,
    begin: beginOAuthAttempt(context),
    pickFiles: beginExportAttempt(context),
    close: context.close,
    refreshSelection: context.refreshSelection,
    select: context.oauth.select,
    submitConfig: context.oauth.submitConfig,
    chooseAccess: context.oauth.chooseAccess
  }
}

function beginOAuthAttempt(
  context: ReturnType<typeof useWizardAttempt>
): UseConnectWizard['begin'] {
  const { active, guard, beginAttempt, scope, oauth, settle, linkedConnections, projectId } =
    context
  return async (): Promise<void> => {
    const entry = active
    if (!entry) return
    // Taken BEFORE the guard: a team bind needs no desktop bridge, and a pick
    // must never outlive the click that made it.
    const pickedTeamRepo = takeTeamPick()
    if (!guard(entry, pickedTeamRepo !== null)) return
    const attempt = beginAttempt(entry)
    if (scope === 'account') {
      const bound = await oauth.startAccount(entry.id, connectOptions(entry))
      settle(entry, attempt, bound)
      return
    }
    const linked = linkedAccountFor(linkedConnections, entry.id)
    const result = await oauth.start(projectId!, entry.id, {
      ...connectOptions(entry),
      linkedConnection: linked ? { id: linked.id, login: linked.account_login } : null,
      teamRepo: pickedTeamRepo
    })
    settle(entry, attempt, result)
  }
}

function beginExportAttempt(
  context: ReturnType<typeof useWizardAttempt>
): UseConnectWizard['pickFiles'] {
  const { active, guard, projectId, beginAttempt, settle, eda } = context
  return async (files: File[]): Promise<void> => {
    const entry = active
    if (!entry || !guard(entry)) return
    const { failConnect } = useOnboardingStore.getState()
    // Explicit, independent of scope: a file connect always needs a project.
    if (!projectId) {
      failConnect(entry.id, NOT_LINKED_ERROR)
      return
    }
    // Bound by count and size BEFORE any file.text() — reading a folder or a
    // multi-GB pick into strings would hang the renderer long before the
    // engine's own validation.
    const pickError = prePickError(entry.id, files)
    if (pickError) {
      failConnect(entry.id, pickError)
      return
    }
    const attempt = beginAttempt(entry)
    const read = await readExportFiles(files)
    // The wizard may have closed during the read — a cancelled attempt must
    // not go on to create and sync a source, nor report a failed read.
    if (attempt.cancelled) return
    const assembled: ExportAssembly =
      read === null ? { ok: false, error: FILE_READ_ERROR } : assembleExportInputs(entry.id, read)
    if (!assembled.ok) {
      // Guidance, not a flight: settle so close() keeps the error retryable.
      failConnect(entry.id, assembled.error)
      settle(entry, attempt, { ok: false })
      return
    }
    const result = await eda.start(projectId, entry.id, assembled.inputs)
    settle(entry, attempt, result)
  }
}

function wizardAvailability(
  active: CatalogEntry | null,
  scope: WizardScope,
  projectId: string | null,
  linkedConnections: readonly Connection[]
) {
  const guard = (entry: CatalogEntry, bindsThroughTeam = false): boolean => {
    const { failConnect } = useOnboardingStore.getState()
    if (scope === 'project' && !projectId) {
      failConnect(entry.id, NOT_LINKED_ERROR)
      return false
    }
    const reusesAccount = scope === 'project' && linkedAccountFor(linkedConnections, entry.id)
    const needsBridge = entry.mode === 'oauth' && !reusesAccount && !bindsThroughTeam
    if (needsBridge && !getDesktopOAuthBridge()) {
      failConnect(entry.id, noBridgeError(entry.name))
      return false
    }
    return true
  }

  const refreshSelection = async (): Promise<SelectableItem[]> => {
    const state = active ? useOnboardingStore.getState().connections[active.id] : undefined
    if (
      scope !== 'project' ||
      !projectId ||
      state?.phase !== 'busy' ||
      state.stage !== 'configure' ||
      !state.sourceId ||
      !state.selectable
    ) {
      throw new Error('No active source selection to refresh.')
    }
    return listSelectable(projectId, state.sourceId, undefined, { refresh: true })
  }

  return { guard, refreshSelection }
}

function settleWizardAttempt(
  attempts: { current: Record<string, Attempt> },
  onConnected: UseConnectWizardOptions['onConnected']
) {
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

  return settle
}
