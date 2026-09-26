// SOLUSDEV-246 (STORE ST5) — the sourcing panel's data hook: THIS IS THE
// BACKEND SEAM for both doors. Derive a torque (pure server arithmetic), submit
// a request (a metered job) and poll it until it settles, select a candidate
// (→ a PLANNED part in the graph), read and save the project's rules. Every
// failure is a message on the state, never a thrown promise.
import { useCallback, useEffect, useMemo, useLayoutEffect, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import type { Entity } from '../../lib/api/resources'
import {
  createSourcingRequest,
  deriveTorque,
  getSourcingRequest,
  getSourcingRules,
  putSourcingRules,
  selectSourcingCandidate,
  type SelectInput,
  type SourcingRequestApi,
  type SourcingRequestInput,
  type SourcingRulesApi,
  type TorqueApi,
  type TorqueInput
} from '../../lib/api/resources.sourcing'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'
import { preferencesForTurn } from '../preferences/preferencesStore'

export type SourcingPhase = 'requirement' | 'searching' | 'candidates' | 'failed' | 'selected'

export interface SourcingActions {
  derive: (input: TorqueInput) => Promise<void>
  submit: (input: SourcingRequestInput) => Promise<void>
  select: (candidateId: string, options?: Omit<SelectInput, 'candidate_id'>) => Promise<void>
  saveRules: (rules: SourcingRulesApi) => Promise<boolean>
  reset: () => void
}

export interface SourcingData {
  readonly phase: SourcingPhase
  readonly rules: SourcingRulesApi | null
  readonly torque: TorqueApi | null
  readonly request: SourcingRequestApi | null
  readonly selected: Entity | null
  readonly error: string | null
  readonly busy: boolean
  readonly actions: SourcingActions
}

export interface SourcingOptions {
  readonly pollMs?: number
}

const DEFAULT_POLL_MS = 1500
const MAX_POLLS = 200

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : "Couldn't reach Solus. Try again in a moment."
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** The string sections of the user's engineering preferences — the API takes
 *  `dict[str, str]`; `schema_version` and timestamps never travel. */
function preferenceSections(raw: Record<string, unknown> | null): Record<string, string> | null {
  if (!raw) return null
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === 'string' && value.trim()) out[key] = value
  }
  return Object.keys(out).length > 0 ? out : null
}

type Settled = { phase: 'candidates' } | { phase: 'failed'; error: string } | null

function settle(latest: SourcingRequestApi): Settled {
  if (latest.status === 'succeeded') return { phase: 'candidates' }
  if (latest.status === 'failed' || latest.status === 'cancelled') {
    return { phase: 'failed', error: latest.error?.message ?? 'Sourcing did not finish.' }
  }
  return null
}

interface PollSinks {
  readonly alive: () => boolean
  readonly onRequest: (request: SourcingRequestApi) => void
  readonly onSettled: (settled: Exclude<Settled, null>) => void
}

/** Re-read the request until it settles; a failed read is retried on the next tick. */
async function pollRequest(
  projectId: string,
  requestId: string,
  pollMs: number,
  sinks: PollSinks
): Promise<void> {
  for (let i = 0; i < MAX_POLLS && sinks.alive(); i += 1) {
    await sleep(pollMs)
    if (!sinks.alive()) return
    const latest = await getSourcingRequest(projectId, requestId).catch(() => null)
    if (!latest || !sinks.alive()) continue
    sinks.onRequest(latest)
    const settled = settle(latest)
    if (settled) {
      sinks.onSettled(settled)
      return
    }
  }
  if (sinks.alive())
    sinks.onSettled({ phase: 'failed', error: 'Sourcing is taking too long; try again later.' })
}

export function useSourcing(projectId: string, options: SourcingOptions = {}): SourcingData {
  const pollMs = options.pollMs ?? DEFAULT_POLL_MS
  const [phase, setPhase] = useState<SourcingPhase>('requirement')
  const [rules, setRules] = useState<SourcingRulesApi | null>(null)
  const [torque, setTorque] = useState<TorqueApi | null>(null)
  const [request, setRequest] = useState<SourcingRequestApi | null>(null)
  const [selected, setSelected] = useState<Entity | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const generation = useWorkspaceSessionGeneration()
  const lease = useMemo(() => ({ live: true, projectId, generation }), [projectId, generation])
  const current = useCallback(
    () => lease.live && workspaceSessionGeneration() === generation,
    [lease, generation]
  )
  useLayoutEffect(() => {
    lease.live = true
    setPhase('requirement')
    setRules(null)
    setTorque(null)
    setRequest(null)
    setSelected(null)
    setError(null)
    setBusy(false)
    return () => {
      lease.live = false
    }
  }, [lease])

  useEffect(() => {
    let cancelled = false
    getSourcingRules(projectId).then(
      (loaded) => {
        if (!cancelled && current()) setRules(loaded)
      },
      () => undefined
    )
    return () => {
      cancelled = true
    }
  }, [projectId, current])

  const { derive, submit } = useRequestActions({
    projectId,
    pollMs,
    current,
    setBusy,
    setError,
    setTorque,
    setSelected,
    setRequest,
    setPhase
  })

  const select = useCallback(
    async (candidateId: string, extra: Omit<SelectInput, 'candidate_id'> = {}): Promise<void> => {
      if (!request || !current()) return
      setBusy(true)
      setError(null)
      try {
        const outcome = await selectSourcingCandidate(projectId, request.id, {
          candidate_id: candidateId,
          ...extra
        })
        if (!current()) return
        setRequest(outcome.request)
        setSelected(outcome.entity)
        setPhase('selected')
      } catch (err) {
        if (current()) setError(messageOf(err))
      } finally {
        if (current()) setBusy(false)
      }
    },
    [projectId, request, current]
  )

  const saveRules = useSaveSourcingRules(projectId, current, setError, setRules)

  const reset = useCallback((): void => {
    setPhase('requirement')
    setRequest(null)
    setSelected(null)
    setError(null)
  }, [])

  const actions = useMemo<SourcingActions>(
    () => ({ derive, submit, select, saveRules, reset }),
    [derive, submit, select, saveRules, reset]
  )
  return { phase, rules, torque, request, selected, error, busy, actions }
}

interface RequestActionsContext {
  projectId: string
  pollMs: number
  current: () => boolean
  setBusy: (busy: boolean) => void
  setError: (error: string | null) => void
  setTorque: (torque: TorqueApi) => void
  setSelected: (selected: Entity | null) => void
  setRequest: (request: SourcingRequestApi) => void
  setPhase: (phase: SourcingPhase) => void
}

function useRequestActions({
  projectId,
  pollMs,
  current,
  setBusy,
  setError,
  setTorque,
  setSelected,
  setRequest,
  setPhase
}: RequestActionsContext): Pick<SourcingActions, 'derive' | 'submit'> {
  const derive = useCallback(
    async (input: TorqueInput): Promise<void> => {
      if (!current()) return
      setBusy(true)
      setError(null)
      try {
        const derived = await deriveTorque(projectId, input)
        if (current()) setTorque(derived)
      } catch (err) {
        if (current()) setError(messageOf(err))
      } finally {
        if (current()) setBusy(false)
      }
    },
    [projectId, current, setBusy, setError, setTorque]
  )

  const submit = useCallback(
    async (input: SourcingRequestInput): Promise<void> => {
      if (!current()) return
      setBusy(true)
      setError(null)
      setSelected(null)
      try {
        const preferences = preferenceSections(
          (await preferencesForTurn()) as Record<string, unknown> | null
        )
        if (!current()) return
        const created = await createSourcingRequest(projectId, {
          ...input,
          ...(preferences ? { preferences } : {})
        })
        if (!current()) return
        setRequest(created.request)
        if (created.request.torque) setTorque(created.request.torque)
        setPhase('searching')
        // The poll outlives this call: the panel shows "searching" until the job settles.
        void pollRequest(projectId, created.request.id, pollMs, {
          alive: current,
          onRequest: setRequest,
          onSettled: (settled) => {
            setPhase(settled.phase)
            if (settled.phase === 'failed') setError(settled.error)
          }
        })
      } catch (err) {
        if (!current()) return
        setPhase('requirement')
        setError(messageOf(err))
      } finally {
        if (current()) setBusy(false)
      }
    },
    [pollMs, projectId, current, setBusy, setError, setSelected, setRequest, setTorque, setPhase]
  )

  return { derive, submit }
}

function useSaveSourcingRules(
  projectId: string,
  current: () => boolean,
  setError: (error: string | null) => void,
  setRules: (rules: SourcingRulesApi) => void
): SourcingActions['saveRules'] {
  return useCallback(
    async (next: SourcingRulesApi): Promise<boolean> => {
      if (!current()) return false
      setError(null)
      try {
        const saved = await putSourcingRules(projectId, next)
        if (!current()) return false
        setRules(saved)
        return true
      } catch (err) {
        if (current()) setError(messageOf(err))
        return false
      }
    },
    [projectId, current, setError, setRules]
  )
}
