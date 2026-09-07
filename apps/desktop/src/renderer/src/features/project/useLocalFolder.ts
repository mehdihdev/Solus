// The LOCAL FOLDER card's data hook (SOLUSDEV-249 / I2). Owns everything that
// talks to the API for a folder linked on THIS machine: the link call (which
// carries the companion instance id + hostname + basename — never the path),
// the unlink (disconnect the local source), open-in-tool, and the view poll —
// fast while a scan runs, slow otherwise, and on window focus. Pure over its
// injected deps so the cadence is testable with fake timers.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import { disconnectSource } from '../../lib/api/resources'
import {
  EMPTY_LOCAL_FOLDER_VIEW,
  getLocalFolder,
  linkLocalFolder,
  openLocalFolderEntity,
  type LinkLocalFolderInput,
  type LocalFolderView,
  type LocalOpenTool,
  type OpenLocalFolderInput,
  type OpenLocalFolderResult
} from '../../lib/api/resources.localfolder'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { useInterval } from '../../lib/useInterval'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import {
  IDLE_POLL_MS,
  SYNCING_POLL_MS,
  folderBasename,
  type LocalFolderStatus
} from './localFolder.constants'

export interface MachineIdentity {
  id: string
  name: string
}

export interface LocalFolderDeps {
  /** This machine, from the desktop bridge; null when it has no companion id. */
  machine: () => Promise<MachineIdentity | null>
  linkLocalFolder: (
    projectId: string,
    input: LinkLocalFolderInput
  ) => Promise<{ source: LocalFolderView['source']; job_id: string }>
  getLocalFolder: (projectId: string, machineId: string) => Promise<LocalFolderView>
  openLocalFolderEntity: (
    projectId: string,
    sourceId: string,
    input: OpenLocalFolderInput
  ) => Promise<OpenLocalFolderResult>
  disconnectSource: (
    projectId: string,
    sourceId: string,
    options: { retainEntities: boolean }
  ) => Promise<unknown>
}

const REAL_DEPS: LocalFolderDeps = {
  machine: async () => (await getDesktopFolderBridge()?.machine()) ?? null,
  linkLocalFolder: (projectId, input) => linkLocalFolder(projectId, input),
  getLocalFolder: (projectId, machineId) => getLocalFolder(projectId, machineId),
  openLocalFolderEntity: (projectId, sourceId, input) =>
    openLocalFolderEntity(projectId, sourceId, input),
  disconnectSource: (projectId, sourceId, options) => disconnectSource(projectId, sourceId, options)
}

export interface LocalFolderController {
  view: LocalFolderView | null
  status: LocalFolderStatus
  /** False once the bridge said this machine has no companion id. */
  machineAvailable: boolean
  link: (path: string) => Promise<void>
  unlink: () => Promise<void>
  /** The tool's answer, a refusal folded into `launched: false`, or null with no source. */
  open: (entityId: string, tool: LocalOpenTool) => Promise<OpenLocalFolderResult | null>
  refresh: () => Promise<void>
}

/** This machine's identity, once: the settled state for rendering decisions,
 *  plus `resolve`, which awaits the same request so a link issued before it
 *  settles (select folder straight after mount) still carries the identity.
 *  `undefined` = not asked yet, `null` = the bridge has no companion id. */
function useMachineIdentity(deps: LocalFolderDeps): {
  machine: MachineIdentity | null | undefined
  resolve: () => Promise<MachineIdentity | null>
} {
  const [machine, setMachine] = useState<MachineIdentity | null | undefined>(undefined)
  const pending = useRef<Promise<MachineIdentity | null>>(Promise.resolve(null))
  useEffect(() => {
    let live = true
    const request = deps.machine().catch(() => null)
    pending.current = request
    void request.then((resolved) => live && setMachine(resolved))
    return () => {
      live = false
    }
  }, [deps])
  const resolve = useCallback(() => pending.current, [])
  return { machine, resolve }
}

export function useLocalFolder(
  projectId: string | null,
  linked: boolean,
  deps: LocalFolderDeps = REAL_DEPS
): LocalFolderController {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const { machine, resolve: resolveMachine } = useMachineIdentity(deps)
  const [view, setView] = useState<LocalFolderView | null>(null)
  const [status, setStatus] = useState<LocalFolderStatus>('idle')
  // A response for a scope the hook has since left (project switch, unlink,
  // unmount) must never paint over the current one.
  const generation = useRef(0)

  const active = fetchEnabled && linked && projectId !== null && !!machine

  const load = useCallback(async (): Promise<void> => {
    if (!active || !projectId || !machine) {
      setView(null)
      setStatus('idle')
      return
    }
    const mine = generation.current
    try {
      const next = await deps.getLocalFolder(projectId, machine.id)
      if (mine !== generation.current) return
      setView(next)
      setStatus('ready')
    } catch {
      if (mine !== generation.current) return
      setView((previous) => {
        setStatus(previous ? 'ready' : 'offline')
        return previous
      })
    }
  }, [active, projectId, machine, deps])

  useEffect(() => {
    generation.current += 1
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])

  const scanning = view?.source?.status === 'syncing'
  useInterval(() => void load(), scanning ? SYNCING_POLL_MS : IDLE_POLL_MS, active)

  useEffect(() => {
    if (!active) return
    const onFocus = (): void => void load()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [active, load])

  const link = useCallback(
    async (path: string): Promise<void> => {
      const resolved = machine ?? (await resolveMachine())
      if (!projectId || !resolved) return
      generation.current += 1
      try {
        const { source } = await deps.linkLocalFolder(projectId, {
          machine_id: resolved.id,
          machine_name: resolved.name,
          folder_name: folderBasename(path)
        })
        setView((previous) => ({ ...(previous ?? EMPTY_LOCAL_FOLDER_VIEW), source }))
        setStatus('ready')
      } catch {
        setStatus('offline')
      }
      await load()
    },
    [projectId, machine, resolveMachine, deps, load]
  )

  const unlink = useCallback(async (): Promise<void> => {
    const source = view?.source
    generation.current += 1
    setView(null)
    setStatus('idle')
    if (!projectId || !source) return
    await deps.disconnectSource(projectId, source.id, { retainEntities: true }).catch(() => null)
  }, [projectId, view, deps])

  const open = useCallback(
    async (entityId: string, tool: LocalOpenTool): Promise<OpenLocalFolderResult | null> => {
      const source = view?.source
      if (!projectId || !source) return null
      try {
        return await deps.openLocalFolderEntity(projectId, source.id, { entity_id: entityId, tool })
      } catch (error) {
        const reason = error instanceof ApiError ? error.message : 'Could not reach Solus'
        return { launched: false, tool, reason }
      }
    },
    [projectId, view, deps]
  )

  return {
    view,
    status,
    machineAvailable: machine !== null,
    link,
    unlink,
    open,
    refresh: load
  }
}
