// SOLUSDEV-317: this machine's SOL-started processes for the open project
// (code-command-execution.md §6). Machine identity comes from the same desktop
// bridge the Code environment row uses; polls every 1 s while any process waits
// for input (§11.3), every 2 s while any runs and every 15 s otherwise;
// inactive (no fetch, no timer) without a project, a machine identity or a
// reachable workspace, and on unmount. Each fresh list is handed to the waker
// (processWake.ts) with the surface's current action mode.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getCodeProcessOutput,
  listCodeProcesses,
  sendCodeProcessInput,
  stopCodeProcess,
  type CodeProcess,
  type ProcessInput,
  type ProcessInputResult,
  type ProcessOutput
} from '../../lib/api/resources.commands'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { useInterval } from '../../lib/useInterval'
import { useMachineIdentity, type MachineIdentity } from '../project/useLocalFolder'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { wakeWaitingProcesses } from './processWake'
import type { SolActionMode } from './solApi'
import { wakeTurn } from './solChatStore'

export const WAITING_POLL_MS = 1_000
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
  sendCodeProcessInput: (
    projectId: string,
    processId: string,
    machineId: string,
    input: ProcessInput
  ) => Promise<ProcessInputResult>
  /** Start a wake turn for any new prompt this renderer owns (§11.3). */
  wake: (projectId: string, processes: readonly CodeProcess[], actionMode: SolActionMode) => void
}

export const REAL_PROCESS_DEPS: ProcessStripDeps = {
  machine: async () => (await getDesktopFolderBridge()?.machine()) ?? null,
  listCodeProcesses: (projectId, machineId) => listCodeProcesses(projectId, machineId),
  getCodeProcessOutput: (projectId, processId, machineId, cursor) =>
    getCodeProcessOutput(projectId, processId, machineId, cursor),
  stopCodeProcess: (projectId, processId, machineId) =>
    stopCodeProcess(projectId, processId, machineId),
  sendCodeProcessInput: (projectId, processId, machineId, input) =>
    sendCodeProcessInput(projectId, processId, machineId, input),
  wake: (projectId, processes, actionMode) =>
    wakeWaitingProcesses(projectId, processes, actionMode, wakeTurn)
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

function toSnapshot(processes: readonly CodeProcess[]): ProcessSnapshot | null {
  return processes.length > 0 ? { processes, readAt: Date.now() } : null
}

/** How often to re-read the list: fastest while anything waits for input. */
export function pollInterval(snapshot: ProcessSnapshot | null): number {
  const processes = snapshot?.processes ?? []
  if (processes.some((p) => p.awaiting_input)) return WAITING_POLL_MS
  return processes.some((p) => p.state === 'running') ? RUNNING_POLL_MS : IDLE_POLL_MS
}

export function useCodeProcesses(
  projectId: string | null,
  deps: ProcessStripDeps,
  refreshSignal: unknown,
  actionMode?: SolActionMode
): CodeProcessesController {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const { machine } = useMachineIdentity(deps)
  const machineId = machine?.id ?? null
  const active = fetchEnabled && projectId !== null && machineId !== null
  const [snapshot, setSnapshot] = useState<ProcessSnapshot | null>(null)
  // A response for a scope the hook has since left must never paint over it.
  const generation = useRef(0)
  // Read at answer time, so a mode switch never refetches.
  const mode = useRef(actionMode)
  useEffect(() => {
    mode.current = actionMode
  }, [actionMode])

  const load = useCallback(async (): Promise<void> => {
    if (!active || !projectId || !machineId) return
    const mine = generation.current
    try {
      const answer = await deps.listCodeProcesses(projectId, machineId)
      if (mine !== generation.current) return
      if (!answer.bridge.connected) return setSnapshot(null)
      if (mode.current) deps.wake(projectId, answer.processes, mode.current)
      setSnapshot(toSnapshot(answer.processes))
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

  useInterval(() => void load(), pollInterval(snapshot), active)

  return { snapshot: active ? snapshot : null, machineId, refresh: load }
}
