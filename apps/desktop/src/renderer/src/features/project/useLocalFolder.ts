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
export function useMachineIdentity(deps: Pick<LocalFolderDeps, 'machine'>): {
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

function isFolderScanning(status: LocalFolderStatus, view: LocalFolderView | null): boolean {
  return status === 'loading' || view?.source?.status === 'syncing'
}

function isCurrentProject(
  scope: { projectId: string | null; live: boolean },
  projectId: string
): boolean {
  return scope.live && scope.projectId === projectId
}

function useLocalFolderScope(projectId: string | null, linked: boolean, deps: LocalFolderDeps) {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const { machine, resolve: resolveMachine } = useMachineIdentity(deps)
  const [view, setView] = useState<LocalFolderView | null>(null)
  const [status, setStatus] = useState<LocalFolderStatus>('idle')
  // A response for a scope the hook has since left (project switch, unlink,
  // unmount) must never paint over the current one.
  const generation = useRef(0)
  const reconnectUntil = useRef(0)
  const scope = useRef({ projectId, linked, live: true })
  const linking = useRef(false)
  const linkVersion = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearReconnectTimer = useCallback((): void => {
    if (reconnectTimer.current !== null) clearTimeout(reconnectTimer.current)
    reconnectTimer.current = null
  }, [])
  useEffect(
    () => () => {
      clearReconnectTimer()
      linkVersion.current += 1
      linking.current = false
      reconnectUntil.current = 0
    },
    [projectId, clearReconnectTimer]
  )
  useEffect(() => {
    scope.current = { projectId, linked, live: true }
    return () => {
      scope.current.live = false
    }
  }, [projectId, linked])

  const active = fetchEnabled && linked && projectId !== null && !!machine

  return {
    projectId,
    machine,
    resolveMachine,
    view,
    setView,
    status,
    setStatus,
    generation,
    reconnectUntil,
    scope,
    linking,
    linkVersion,
    reconnectTimer,
    clearReconnectTimer,
    active
  }
}

function useLocalFolderReads(state: ReturnType<typeof useLocalFolderScope>, deps: LocalFolderDeps) {
  const {
    projectId,
    machine,
    view,
    setView,
    status,
    setStatus,
    generation,
    reconnectUntil,
    linking,
    clearReconnectTimer,
    active
  } = state
  const readView = useCallback(
    async (project: string, identity: MachineIdentity): Promise<void> => {
      const mine = generation.current
      try {
        const next = await deps.getLocalFolder(project, identity.id)
        if (mine !== generation.current) return
        if (next.bridge.connected) clearReconnectTimer()
        setView(next)
        setStatus(
          !next.bridge.connected && Date.now() < reconnectUntil.current ? 'loading' : 'ready'
        )
      } catch {
        if (mine !== generation.current) return
        setView((previous) => {
          setStatus(
            Date.now() < reconnectUntil.current ? 'loading' : previous ? 'ready' : 'offline'
          )
          return previous
        })
      }
    },
    [deps, clearReconnectTimer, generation, reconnectUntil, setStatus, setView]
  )

  const load = useCallback(async (): Promise<void> => {
    if (active && projectId && machine && !linking.current) await readView(projectId, machine)
  }, [active, projectId, machine, readView, linking])

  useEffect(() => {
    generation.current += 1
    let live = true
    void Promise.resolve().then(async () => {
      if (live) await load()
    })
    return () => {
      live = false
      generation.current += 1
    }
  }, [load, generation])

  const scanning = isFolderScanning(status, view)
  useInterval(() => void load(), scanning ? SYNCING_POLL_MS : IDLE_POLL_MS, active)

  useEffect(() => {
    if (!active) return
    const onFocus = (): void => void load()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [active, load])

  return { readView, load }
}

function useFolderLink(
  state: ReturnType<typeof useLocalFolderScope>,
  readView: ReturnType<typeof useLocalFolderReads>['readView'],
  deps: LocalFolderDeps
): LocalFolderController['link'] {
  const {
    projectId,
    machine,
    resolveMachine,
    setView,
    setStatus,
    generation,
    reconnectUntil,
    scope,
    linking,
    linkVersion,
    reconnectTimer,
    clearReconnectTimer
  } = state
  const link = useCallback(
    (path: string): Promise<void> =>
      linkFolderAttempt(
        path,
        {
          projectId,
          machine,
          resolveMachine,
          setView,
          setStatus,
          generation,
          reconnectUntil,
          scope,
          linking,
          linkVersion,
          reconnectTimer,
          clearReconnectTimer
        },
        readView,
        deps
      ),
    [
      projectId,
      machine,
      resolveMachine,
      deps,
      readView,
      clearReconnectTimer,
      generation,
      linkVersion,
      linking,
      reconnectTimer,
      reconnectUntil,
      scope,
      setStatus,
      setView
    ]
  )

  return link
}

export function useLocalFolder(
  projectId: string | null,
  linked: boolean,
  deps: LocalFolderDeps = REAL_DEPS
): LocalFolderController {
  const state = useLocalFolderScope(projectId, linked, deps)
  const { readView, load } = useLocalFolderReads(state, deps)
  const link = useFolderLink(state, readView, deps)
  const {
    view,
    setView,
    status,
    setStatus,
    generation,
    reconnectUntil,
    clearReconnectTimer,
    linkVersion,
    linking,
    active,
    machine
  } = state
  const unlink = useCallback(async (): Promise<void> => {
    const source = view?.source
    generation.current += 1
    reconnectUntil.current = 0
    clearReconnectTimer()
    linkVersion.current += 1
    linking.current = false
    setView(null)
    setStatus('idle')
    if (!projectId || !source) return
    await deps.disconnectSource(projectId, source.id, { retainEntities: true }).catch(() => null)
  }, [
    projectId,
    view,
    deps,
    clearReconnectTimer,
    generation,
    linkVersion,
    linking,
    reconnectUntil,
    setStatus,
    setView
  ])

  const open = useCallback(
    async (entityId: string, tool: LocalOpenTool): Promise<OpenLocalFolderResult | null> => {
      const source = view?.source
      if (!projectId || !source || status === 'loading') return null
      try {
        return await deps.openLocalFolderEntity(projectId, source.id, { entity_id: entityId, tool })
      } catch (error) {
        const reason = error instanceof ApiError ? error.message : 'Could not reach Solus'
        return { launched: false, tool, reason }
      }
    },
    [projectId, view, status, deps]
  )

  return {
    view: active ? view : null,
    status: active ? status : 'idle',
    machineAvailable: machine !== null,
    link,
    unlink,
    open,
    refresh: load
  }
}

type FolderLinkContext = Pick<
  ReturnType<typeof useLocalFolderScope>,
  | 'projectId'
  | 'machine'
  | 'resolveMachine'
  | 'setView'
  | 'setStatus'
  | 'generation'
  | 'reconnectUntil'
  | 'scope'
  | 'linking'
  | 'linkVersion'
  | 'reconnectTimer'
  | 'clearReconnectTimer'
>

async function linkFolderAttempt(
  path: string,
  context: FolderLinkContext,
  readView: ReturnType<typeof useLocalFolderReads>['readView'],
  deps: LocalFolderDeps
): Promise<void> {
  const {
    projectId,
    machine,
    resolveMachine,
    setView,
    setStatus,
    generation,
    reconnectUntil,
    scope,
    linking,
    linkVersion,
    reconnectTimer,
    clearReconnectTimer
  } = context
  if (!projectId || !isCurrentProject(scope.current, projectId)) return
  const version = ++linkVersion.current
  const ownsAttempt = (): boolean =>
    version === linkVersion.current && isCurrentProject(scope.current, projectId)
  const resolved = machine ?? (await resolveMachine())
  if (!resolved || !ownsAttempt()) return
  generation.current += 1
  clearReconnectTimer()
  linking.current = true
  reconnectUntil.current = Date.now() + 30_000
  setView(null)
  setStatus('loading')
  const current = (): boolean => ownsAttempt() && scope.current.linked
  reconnectTimer.current = setTimeout(() => {
    if (!current()) return
    reconnectTimer.current = null
    linkVersion.current += 1
    generation.current += 1
    linking.current = false
    reconnectUntil.current = 0
    setView((previous) => {
      setStatus(previous ? 'ready' : 'offline')
      return previous
    })
    // Reconcile the source through a read only. A timed-out POST is never replayed.
    void readView(projectId, resolved)
  }, 30_000)
  const finishAttempt = (): void => {
    if (version === linkVersion.current) linking.current = false
  }
  try {
    await deps.linkLocalFolder(projectId, {
      machine_id: resolved.id,
      machine_name: resolved.name,
      folder_name: folderBasename(path)
    })
    finishAttempt()
    if (current()) await readView(projectId, resolved)
  } catch {
    finishAttempt()
    if (current()) {
      clearReconnectTimer()
      reconnectUntil.current = 0
      setStatus('offline')
    }
  }
}
