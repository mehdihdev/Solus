// The Code environment row's data hook (SOLUSDEV-250 / I3). Reads this
// machine's view — the linked folder plus the interpreter and venv that run
// it — for the current project, but only once the project has a `local`
// source linked HERE (the machine identity comes from the same desktop bridge
// the LOCAL FOLDER card uses). Polls slowly and on window focus; pure over its
// injected deps so the cadence is testable with fake timers.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Source } from '../../lib/api/resources'
import { getCodeEnvironment, type CodeEnvironmentView } from '../../lib/api/resources.codeenv'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { useInterval } from '../../lib/useInterval'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { CODE_ENVIRONMENT_POLL_MS, localSourceForMachine } from './codeEnvironment.constants'
import type { LocalFolderStatus } from './localFolder.constants'
import { useMachineIdentity, type MachineIdentity } from './useLocalFolder'

export interface CodeEnvironmentDeps {
  /** This machine, from the desktop bridge; null when it has no companion id. */
  machine: () => Promise<MachineIdentity | null>
  getCodeEnvironment: (projectId: string, machineId: string) => Promise<CodeEnvironmentView>
}

const REAL_DEPS: CodeEnvironmentDeps = {
  machine: async () => (await getDesktopFolderBridge()?.machine()) ?? null,
  getCodeEnvironment: (projectId, machineId) => getCodeEnvironment(projectId, machineId)
}

export interface CodeEnvironmentController {
  view: CodeEnvironmentView | null
  status: LocalFolderStatus
  /** The project's local source linked on THIS machine; null hides the row. */
  source: Source | null
  refresh: () => Promise<void>
}

export function useCodeEnvironment(
  projectId: string | null,
  sources: readonly Source[],
  deps: CodeEnvironmentDeps = REAL_DEPS
): CodeEnvironmentController {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const { machine } = useMachineIdentity(deps)
  const source = localSourceForMachine(sources, machine?.id ?? null)
  const [view, setView] = useState<CodeEnvironmentView | null>(null)
  const [status, setStatus] = useState<LocalFolderStatus>('idle')
  // A response for a scope the hook has since left (project switch, unlink,
  // unmount) must never paint over the current one.
  const generation = useRef(0)
  // Whether a view has been painted: an error after one keeps it ("ready"),
  // an error before one reads "offline". A ref, so the catch path never
  // nests one state update inside another's updater.
  const hasView = useRef(false)

  const machineId = machine?.id ?? null
  const active = fetchEnabled && projectId !== null && machineId !== null && source !== null

  const load = useCallback(async (): Promise<void> => {
    // Inactive scopes render idle by derivation below — no state write here,
    // so the effect that calls `load` never sets state synchronously.
    if (!active || !projectId || !machineId) return
    const mine = generation.current
    try {
      const next = await deps.getCodeEnvironment(projectId, machineId)
      if (mine !== generation.current) return
      hasView.current = true
      setView(next)
      setStatus('ready')
    } catch {
      if (mine !== generation.current) return
      setStatus(hasView.current ? 'ready' : 'offline')
    }
  }, [active, projectId, machineId, deps])

  useEffect(() => {
    generation.current += 1
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])

  useInterval(() => void load(), CODE_ENVIRONMENT_POLL_MS, active)

  useEffect(() => {
    if (!active) return
    const onFocus = (): void => void load()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [active, load])

  return {
    view: active ? view : null,
    status: active ? status : 'idle',
    source,
    refresh: load
  }
}
