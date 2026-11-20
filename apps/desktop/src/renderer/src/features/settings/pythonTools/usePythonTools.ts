// SOLUSDEV-329 — Settings › Python for local tools state, over
// window.solus.mcpRuntime (docs/architecture/mcp-fork-runtime.md §9). Lifted
// to the page so the section and the Needs-attention card share one copy.
// Every call is through the typed bridge; null outside Electron.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  InstallManagedResult,
  Candidate,
  ChoiceView,
  ChooseResult,
  ForkStatus,
  McpRuntimeBridge,
  ProvisionTrigger,
  RuntimeErrorCode
} from '../../../../../main/mcpRuntime/channels'
import {
  acceptPush,
  failedForks,
  firstFailingCode,
  forksNeedingSetup,
  isRunning,
  newRun,
  type RunView
} from './pythonToolsRun'
import {
  reportInterpreterChosen,
  reportManagedConsent,
  reportSetupFinished,
  type InterpreterSource
} from './pythonToolsEvents'

export type Phase = 'detecting' | 'ready' | 'error'

export interface PythonToolsActions {
  chooseCandidate: (candidate: Candidate) => void
  /** Choose… — main's file picker. */
  pick: () => void
  /** The managed option: chosen when installed, otherwise the consent offer opens. */
  chooseManaged: () => void
  acceptManaged: () => void
  declineManaged: () => void
  /** Install / Set up now: every tool. */
  setupAll: () => void
  /** Needs-attention `Set up local tools`: only the tools that need it. */
  setupNeeded: () => void
  /** Repair: only the tools that failed. */
  repair: () => void
  cancel: () => void
}

export interface PythonTools {
  available: boolean
  phase: Phase
  candidates: readonly Candidate[]
  forks: readonly ForkStatus[]
  choice: ChoiceView | null
  chooseError: RuntimeErrorCode | null
  actionFailed: boolean
  choiceChanged: boolean
  /** The managed offer is open (none found, or the managed option was picked). */
  offerOpen: boolean
  run: RunView | null
  running: boolean
  needsSetup: readonly string[]
  failed: readonly string[]
  actions: PythonToolsActions
}

export function getMcpRuntimeBridge(): McpRuntimeBridge | null {
  const solus = (window as unknown as { solus?: { mcpRuntime?: McpRuntimeBridge } }).solus
  return solus?.mcpRuntime ?? null
}

interface Loaded {
  candidates: Candidate[]
  forks: ForkStatus[]
  choice: ChoiceView
}

function useLoad(bridge: McpRuntimeBridge | null): {
  phase: Phase
  loaded: Loaded | null
  reload: () => void
  refreshStatus: () => void
} {
  const [phase, setPhase] = useState<Phase>('detecting')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const reload = useCallback(() => {
    if (!bridge) return
    Promise.all([bridge.detect(), bridge.status(), bridge.getChoice()]).then(
      ([d, s, choice]) => {
        setLoaded({ candidates: d.candidates, forks: s.forks, choice })
        setPhase('ready')
      },
      () => setPhase((p) => (p === 'ready' ? p : 'error'))
    )
  }, [bridge])
  const refreshStatus = useCallback(() => {
    bridge?.status().then(
      (s) => setLoaded((l) => (l ? { ...l, forks: s.forks } : l)),
      () => undefined
    )
  }, [bridge])
  useEffect(reload, [reload])
  return { phase, loaded, reload, refreshStatus }
}

/** Fold pushes into the run; side effects run once per finished run. */
function useRun(
  bridge: McpRuntimeBridge | null,
  onFinished: (run: RunView) => void
): {
  run: RunView | null
  start: (
    kind: RunView['kind'],
    trigger: ProvisionTrigger,
    call: () => Promise<InstallManagedResult>
  ) => void
  failed: boolean
} {
  const [run, setRun] = useState<RunView | null>(null)
  const [failed, setFailed] = useState(false)
  const handled = useRef<RunView | null>(null)
  useEffect(
    () => bridge?.onProgress(({ runId, event }) => setRun((r) => acceptPush(r, runId, event))),
    [bridge]
  )
  useEffect(() => {
    if (run?.done && handled.current !== run) {
      handled.current = run
      onFinished(run)
    }
  }, [run, onFinished])
  const start = useCallback(
    (
      kind: RunView['kind'],
      trigger: ProvisionTrigger,
      call: () => Promise<InstallManagedResult>
    ) => {
      setFailed(false)
      setRun(newRun(kind, trigger))
      call().then(
        // runId null: the user said no in main's own confirmation — nothing ran.
        ({ runId }) =>
          setRun((r) => (runId === null ? null : r && r.runId === null ? { ...r, runId } : r)),
        () => {
          setFailed(true) // busy / helper unavailable: nothing ran
          setRun(null)
        }
      )
    },
    []
  )
  return { run, start, failed }
}

export function usePythonTools(bridge: McpRuntimeBridge | null): PythonTools {
  const { phase, loaded, reload, refreshStatus } = useLoad(bridge)
  const [chooseError, setChooseError] = useState<RuntimeErrorCode | null>(null)
  const [choiceChanged, setChoiceChanged] = useState(false)
  const [offer, setOffer] = useState<'auto' | 'open' | 'declined'>('auto')

  const adoptChoice = useCallback(
    (result: ChooseResult, source: InterpreterSource) => {
      if (!result.ok) {
        setChooseError(result.error_code === 'cancelled' ? null : result.error_code)
        return
      }
      if (result.version_minor) reportInterpreterChosen(source, result.version_minor)
      setChooseError(null)
      setChoiceChanged(true)
      setOffer('auto')
      reload()
    },
    [reload]
  )
  const choose = useCallback(
    (request: Parameters<McpRuntimeBridge['choose']>[0], source: InterpreterSource) => {
      bridge?.choose(request).then(
        (r) => adoptChoice(r, source),
        () => setChooseError('internal')
      )
    },
    [bridge, adoptChoice]
  )

  const onFinished = useCallback(
    (done: RunView) => {
      if (done.kind === 'install') {
        if (done.done?.outcome === 'ok') choose({ mode: 'managed' }, 'managed')
        return
      }
      reportSetupFinished({
        outcome: done.done?.outcome ?? 'failed',
        failedForks: done.done?.failed ?? 0,
        errorCode: firstFailingCode(done),
        trigger: done.trigger
      })
      // Old envs keep passing trust, so only a fully ok run on the new base may
      // drop the "choice changed" marking; cancelled/failed/partial keep it.
      if (done.done?.outcome === 'ok') setChoiceChanged(false)
      refreshStatus()
    },
    [choose, refreshStatus]
  )
  const { run, start, failed: actionFailed } = useRun(bridge, onFinished)

  const candidates = loaded?.candidates ?? []
  const forks = loaded?.forks ?? []
  const needsSetup = useMemo(
    () => forksNeedingSetup(loaded?.forks ?? [], choiceChanged),
    [loaded?.forks, choiceChanged]
  )
  const managedInstalled = candidates.some((c) => c.source === 'managed' && c.supported)
  const noneSupported = candidates.every((c) => !c.supported)
  const offerOpen =
    offer === 'open' || (offer === 'auto' && noneSupported && loaded?.choice.mode !== 'managed')

  const provision = (trigger: ProvisionTrigger, forkList?: string[]): void => {
    if (!bridge) return
    const request = forkList ? { trigger, forks: forkList } : { trigger }
    start('provision', trigger, () => bridge.provision(request))
  }

  const actions: PythonToolsActions = {
    chooseCandidate: (c) => choose({ mode: 'path', path: c.path }, 'detected'),
    pick: () => choose({ mode: 'path' }, 'picked'),
    chooseManaged: () =>
      managedInstalled ? choose({ mode: 'managed' }, 'managed') : setOffer('open'),
    acceptManaged: () => {
      if (!bridge) return
      reportManagedConsent(true)
      start('install', 'settings', () => bridge.installManaged({ consent: true }))
    },
    declineManaged: () => {
      reportManagedConsent(false)
      setOffer('declined')
    },
    setupAll: () => provision('settings'),
    setupNeeded: () => provision('settings', [...needsSetup]),
    repair: () => provision('repair', failedForks(run)),
    cancel: () => {
      if (run?.runId) void bridge?.cancel({ runId: run.runId }).catch(() => undefined)
    }
  }

  return {
    available: bridge !== null,
    phase,
    candidates,
    forks,
    choice: loaded?.choice ?? null,
    chooseError,
    actionFailed,
    choiceChanged,
    offerOpen,
    run,
    running: isRunning(run),
    needsSetup,
    failed: isRunning(run) ? [] : failedForks(run),
    actions
  }
}
