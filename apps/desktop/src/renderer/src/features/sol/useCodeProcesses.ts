// SOLUSDEV-317: this machine's SOL-started processes for the open project
// (code-command-execution.md §6). Machine identity comes from the same desktop
// bridge the Code environment row uses; polls every 2 s while any process runs
// and every 15 s otherwise; inactive (no fetch, no timer) without a project,
// a machine identity or a reachable workspace, and on unmount.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getCodeProcessOutput,
  listCodeProcesses,
  stopCodeProcess,
  type CodeProcess,
  type ProcessOutput
} from '../../lib/api/resources.commands'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { useInterval } from '../../lib/useInterval'
import { useMachineIdentity, type MachineIdentity } from '../project/useLocalFolder'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export const RUNNING_POLL_MS = 2_000
export const IDLE_POLL_MS = 15_000

export interface ProcessStripDeps {
  machine: () => Promise<MachineIdentity | null>
  listCodeProcesses: typeof listCodeProcesses
  getCodeProcessOutput: (
    projectId: string,
    processId: string,
    machineId: string,
    cursor: number
  ) => Promise<ProcessOutput>
  stopCodeProcess: (projectId: string, processId: string, machineId: string) => Promise<unknown>
}

export const REAL_PROCESS_DEPS: ProcessStripDeps = {
  machine: async () => (await getDesktopFolderBridge()?.machine()) ?? null,
  listCodeProcesses: (projectId, machineId) => listCodeProcesses(projectId, machineId),
  getCodeProcessOutput: (projectId, processId, machineId, cursor) =>
    getCodeProcessOutput(projectId, processId, machineId, cursor),
  stopCodeProcess: (projectId, processId, machineId) =>
    stopCodeProcess(projectId, processId, machineId)
}

export interface ProcessSnapshot {
  readonly processes: readonly CodeProcess[]
  /** When the list was read — elapsed times are measured against it. */
  readonly readAt: number
}

export interface CodeProcessesController {
  /** Null while hidden: inactive, offline, failed or nothing to show. */
  snapshot: ProcessSnapshot | null
  machineId: string | null
  refresh: () => Promise<void>
}

export function useCodeProcesses(
  projectId: string | null,
  deps: ProcessStripDeps,
  refreshSignal: unknown
): CodeProcessesController {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const { machine } = useMachineIdentity(deps)
  const machineId = machine?.id ?? null
  const active = fetchEnabled && projectId !== null && machineId !== null
  const [snapshot, setSnapshot] = useState<ProcessSnapshot | null>(null)
  // A response for a scope the hook has since left must never paint over it.
  const generation = useRef(0)

  const load = useCallback(async (): Promise<void> => {
    if (!active || !projectId || !machineId) return
    const mine = generation.current
    try {
      const answer = await deps.listCodeProcesses(projectId, machineId)
      if (mine !== generation.current) return
      setSnapshot(
        answer.bridge.connected && answer.processes.length > 0
          ? { processes: answer.processes, readAt: Date.now() }
          : null
      )
    } catch {
      if (mine === generation.current) setSnapshot(null)
    }
  }, [active, projectId, machineId, deps])

  // The first read is scheduled, not called inline: its setState then lands in
  // a timer callback rather than synchronously inside this effect.
  useEffect(() => {
    generation.current += 1
    const first = setTimeout(() => void load(), 0)
    return () => {
      clearTimeout(first)
      generation.current += 1
    }
  }, [load, refreshSignal])

  const running = snapshot?.processes.some((p) => p.state === 'running') ?? false
  useInterval(() => void load(), running ? RUNNING_POLL_MS : IDLE_POLL_MS, active)

  return { snapshot: active ? snapshot : null, machineId, refresh: load }
}
