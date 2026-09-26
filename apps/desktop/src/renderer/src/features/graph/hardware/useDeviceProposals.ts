// Per-device proposal state (SOLUSDEV-250 P3). Every pending device with a
// stable identity is interrogated automatically — safely, ping and listen only —
// in the order it appears, at most two at a time. A silent device is asked
// again twice (5 s, 15 s); a failed request keeps the backend's words; nothing
// is written before the user's Add (ADR-012).
//
// ponytail: one module-level store, not per-hook state — the canvas-edge rail
// and Add › Hardware both render DevicesFound, and two independent schedulers
// would open the same serial port twice (a busy port reads as silence).
import { useCallback, useEffect, useMemo } from 'react'
import { create } from 'zustand'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  acceptHardwareSuggestion,
  confirmDetected,
  proposeDetected,
  type ConfirmIn,
  type ConfirmOut,
  type ConfirmTarget,
  type DetectedDeviceOut,
  type ProposalOut
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { awaitMark, startConfirmation } from '../../../lib/perf/marks'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { hardwareErrorText, robotIdFromMessage } from './detected'
import { useProposalSources } from './useProposalSources'
import {
  AMBIGUOUS_NOTE,
  connectionOnly,
  defaultAccepted,
  pendingDevices,
  type DeviceCardState
} from './deviceCardRules'

export interface ConfirmInput {
  name?: string
  target: ConfirmTarget
  repoConfigId?: string
}

export interface DeviceProposals {
  cards: DeviceCardState[]
  confirm: (ref: string, input: ConfirmInput) => Promise<ConfirmOut | null>
  accept: (ref: string, suggestionId: string) => Promise<boolean>
  dismiss: (ref: string) => void
  retry: (ref: string) => void
}

interface ProposalsStore {
  generation: number
  projectId: string | null
  sourceKey: string
  sourceRefs: string[] | null
  sourceError: string | null
  states: Record<string, DeviceCardState>
  appearances: Record<string, symbol>
  dismissed: ReadonlySet<string>
}

const MAX_IN_FLIGHT = 2
const SILENT_BACKOFF_MS = [5_000, 15_000] as const
const NO_CARDS: Record<string, DeviceCardState> = {}
const EMPTY: ProposalsStore = {
  generation: -1,
  projectId: null,
  sourceKey: '',
  sourceRefs: null,
  sourceError: null,
  states: NO_CARDS,
  appearances: {},
  dismissed: new Set()
}

const useStore = create<ProposalsStore>()(() => EMPTY)
const inFlight = new Set<string>()
const timers = new Map<string, ReturnType<typeof setTimeout>>()
let consumers = 0

function clearTimer(ref: string): void {
  const timer = timers.get(ref)
  if (timer !== undefined) clearTimeout(timer)
  timers.delete(ref)
}

/** Timers belong to the mounted consumers; an in-flight request belongs to the
 *  network — it resolves and unregisters itself, so it is never cleared here
 *  (clearing it let a remount open the same port twice, and a busy port reads
 *  as silence). */
function clearTimers(): void {
  for (const ref of [...timers.keys()]) clearTimer(ref)
}

/** Test seam: forget every card, timer and in-flight request. */
export function resetDeviceProposals(): void {
  clearTimers()
  inFlight.clear()
  consumers = 0
  useStore.setState(EMPTY)
}

/** Still mounted somewhere, and still the same project — mirrors robotSession's current(). */
function current(projectId: string, generation: number): boolean {
  const store = useStore.getState()
  return (
    consumers > 0 &&
    store.projectId === projectId &&
    store.generation === generation &&
    generation === workspaceSessionGeneration()
  )
}

function currentAppearance(
  projectId: string,
  generation: number,
  ref: string,
  appearance: symbol
): boolean {
  return current(projectId, generation) && useStore.getState().appearances[ref] === appearance
}

type Patch = Partial<DeviceCardState> | null
function patch(ref: string, update: Patch | ((card: DeviceCardState) => Patch)): void {
  useStore.setState((store) => {
    const card = store.states[ref]
    const next = card && (typeof update === 'function' ? update(card) : update)
    return next ? { states: { ...store.states, [ref]: { ...card, ...next } } } : store
  })
}

function initialCard(ref: string, device: DetectedDeviceOut): DeviceCardState {
  return {
    ref,
    device,
    status: device.ambiguous ? 'failed' : 'proposing',
    proposal: null,
    error: device.ambiguous ? AMBIGUOUS_NOTE : null,
    conflictRobotId: null,
    result: null,
    attempts: 0
  }
}

type Cards = Record<string, DeviceCardState>

/** The known card for a device, refreshed only when the device object changed. */
function mergedCard(
  known: DeviceCardState | undefined,
  device: DetectedDeviceOut
): DeviceCardState {
  const ref = device.device_ref ?? ''
  if (!known) return initialCard(ref, device)
  return known.device === device ? known : { ...known, device }
}

function sameCards(previous: Cards, next: Cards): boolean {
  const refs = Object.keys(next)
  return (
    refs.length === Object.keys(previous).length && refs.every((ref) => previous[ref] === next[ref])
  )
}

/** Cards for the pending set; a device that left takes its timer with it. */
function rebuildCards(previous: Cards, pending: readonly DetectedDeviceOut[]): Cards {
  const states: Cards = {}
  for (const device of pending) {
    const ref = device.device_ref ?? ''
    states[ref] = mergedCard(previous[ref], device)
  }
  for (const ref of Object.keys(previous)) if (!states[ref]) clearTimer(ref)
  return states
}

/** A dismissal lasts while the device stays listed — a re-plug shows it again. */
function prunedDismissals(
  dismissed: ReadonlySet<string>,
  listed: ReadonlySet<string>
): ReadonlySet<string> {
  const kept = [...dismissed].filter((ref) => listed.has(ref))
  return kept.length === dismissed.size ? dismissed : new Set(kept)
}

function applySourceError(states: Cards, error: string | null): void {
  if (!error) return
  for (const ref of Object.keys(states)) states[ref] = { ...states[ref], status: 'failed', error }
}

function sourceOptions(): { source_refs: string[] } | undefined {
  const refs = useStore.getState().sourceRefs
  return refs?.length ? { source_refs: refs } : undefined
}
function requestProposal(projectId: string, ref: string): Promise<ProposalOut> {
  const options = sourceOptions()
  return options ? proposeDetected(projectId, ref, options) : proposeDetected(projectId, ref)
}

/** Rebuild the card map from the pending set. A no-op rebuild keeps the store
 *  identity so consumers do not re-render. */
function reconcile(
  projectId: string | null,
  generation: number,
  pending: readonly DetectedDeviceOut[],
  listed: ReadonlySet<string>,
  sources: ReturnType<typeof useProposalSources>
): void {
  useStore.setState((store) => {
    const reset =
      store.projectId !== projectId ||
      store.generation !== generation ||
      store.sourceKey !== sources.key
    if (reset) clearTimers()
    const previous = reset ? NO_CARDS : store.states
    const states = rebuildCards(previous, pending)
    applySourceError(states, sources.error)
    const appearances = Object.fromEntries(
      Object.keys(states).map((ref) => [ref, (!reset && store.appearances[ref]) || Symbol(ref)])
    )
    const dismissed = prunedDismissals(reset ? new Set() : store.dismissed, listed)
    const unchanged = !reset && dismissed === store.dismissed && sameCards(previous, states)
    return unchanged
      ? store
      : {
          projectId,
          generation,
          sourceKey: sources.key,
          sourceRefs: sources.refs,
          sourceError: sources.error,
          states,
          appearances,
          dismissed
        }
  })
}

function scheduleRetry(
  projectId: string,
  generation: number,
  ref: string,
  appearance: symbol,
  attempts: number
): void {
  const delay = SILENT_BACKOFF_MS[attempts - 1]
  if (delay === undefined) return
  clearTimer(ref)
  timers.set(
    ref,
    setTimeout(() => {
      timers.delete(ref)
      if (!currentAppearance(projectId, generation, ref, appearance)) return
      patch(ref, (card) => (card.status === 'silent' ? { status: 'proposing' } : null))
      schedule(projectId)
    }, delay)
  )
}

async function propose(
  projectId: string,
  generation: number,
  ref: string,
  appearance: symbol
): Promise<void> {
  try {
    const proposal = await requestProposal(projectId, ref)
    if (!currentAppearance(projectId, generation, ref, appearance)) return
    const attempts = (useStore.getState().states[ref]?.attempts ?? 0) + 1
    const silent = proposal.driver_id === null
    patch(ref, { proposal, status: silent ? 'silent' : 'proposed', error: null, attempts })
    if (silent) scheduleRetry(projectId, generation, ref, appearance, attempts)
  } catch (failure) {
    if (!currentAppearance(projectId, generation, ref, appearance)) return
    patch(ref, (card) => ({
      status: 'failed',
      error: hardwareErrorText(failure),
      attempts: card.attempts + 1
    }))
  } finally {
    inFlight.delete(ref)
    // The slot may now serve whichever project is current — possibly a new one
    // that is waiting on this very device.
    const now = useStore.getState().projectId
    if (now) schedule(now)
  }
}

/** Start the next interrogations in device order, up to the in-flight cap. */
function schedule(projectId: string): void {
  const generation = useStore.getState().generation
  if (
    !current(projectId, generation) ||
    useStore.getState().sourceRefs === null ||
    useStore.getState().sourceError
  )
    return
  for (const card of Object.values(useStore.getState().states)) {
    if (inFlight.size >= MAX_IN_FLIGHT) return
    if (card.status !== 'proposing' || card.device.ambiguous || inFlight.has(card.ref)) continue
    inFlight.add(card.ref)
    void propose(projectId, generation, card.ref, useStore.getState().appearances[card.ref])
  }
}

function conflictRobotId(failure: unknown): string | null {
  return failure instanceof ApiError && failure.status === 409
    ? robotIdFromMessage(failure.message)
    : null
}

function confirmBody(proposal: ProposalOut, input: ConfirmInput): ConfirmIn {
  const target: ConfirmTarget =
    input.target.kind === 'new' && input.name ? { kind: 'new', name: input.name } : input.target
  return {
    target,
    accepted: defaultAccepted(proposal),
    ...(input.repoConfigId ? { repo_config_id: input.repoConfigId } : {}),
    connection_only: connectionOnly(proposal),
    start_session: !connectionOnly(proposal),
    window_seconds: 1
  }
}

function settled(card: DeviceCardState | undefined): card is DeviceCardState {
  return card !== undefined && card.status !== 'confirming' && card.status !== 'done'
}

function usePendingDeviceCards(
  projectId: string | null,
  devices: DetectedDeviceOut[] | null,
  entities: readonly Entity[] | null
): { cards: DeviceCardState[]; generation: number } {
  const generation = useWorkspaceSessionGeneration()
  const sources = useProposalSources(projectId)
  // Cards belong to the project that produced them; a switch shows nothing
  // until reconcile() has run for the new project.
  const states = useStore((store) =>
    store.projectId === projectId && store.generation === generation ? store.states : NO_CARDS
  )
  const dismissed = useStore((store) => store.dismissed)
  const pending = useMemo(
    () => pendingDevices(devices ?? [], entities, dismissed),
    [devices, entities, dismissed]
  )
  useEffect(() => {
    consumers += 1
    return () => {
      consumers -= 1
      if (consumers === 0) clearTimers()
    }
  }, [])
  useEffect(() => {
    const listed = new Set(
      (devices ?? []).flatMap((device) => (device.device_ref ? [device.device_ref] : []))
    )
    reconcile(projectId, generation, pending, listed, {
      key: sources.key,
      refs: sources.refs,
      error: sources.error
    })
    if (projectId) schedule(projectId)
  }, [projectId, generation, pending, devices, sources.key, sources.refs, sources.error])
  const cards = useMemo(
    () => pending.flatMap((device) => states[device.device_ref ?? ''] ?? []),
    [pending, states]
  )

  return { cards, generation }
}

export function useDeviceProposals(
  projectId: string | null,
  devices: DetectedDeviceOut[] | null,
  entities: readonly Entity[] | null
): DeviceProposals {
  const { cards, generation } = usePendingDeviceCards(projectId, devices, entities)
  const confirm = useDeviceConfirmation(projectId, generation)

  const accept = useCallback(
    async (ref: string, suggestionId: string): Promise<boolean> => {
      if (
        !projectId ||
        !current(projectId, generation) ||
        !settled(useStore.getState().states[ref])
      )
        return false
      const appearance = useStore.getState().appearances[ref]
      patch(ref, { status: 'confirming', error: null })
      try {
        await acceptHardwareSuggestion(projectId, suggestionId)
        if (!currentAppearance(projectId, generation, ref, appearance)) return false
        patch(ref, { status: 'done' })
        return true
      } catch (failure) {
        if (currentAppearance(projectId, generation, ref, appearance))
          patch(ref, { status: 'failed', error: hardwareErrorText(failure) })
        return false
      }
    },
    [projectId, generation]
  )

  const dismiss = useCallback(
    (ref: string) => {
      if (!projectId || !current(projectId, generation)) return
      useStore.setState((store) => ({ dismissed: new Set([...store.dismissed, ref]) }))
    },
    [projectId, generation]
  )

  const retry = useCallback(
    (ref: string) => {
      if (!projectId || !current(projectId, generation)) return
      clearTimer(ref)
      patch(ref, (card) =>
        settled(card) && !card.device.ambiguous ? { status: 'proposing', error: null } : null
      )
      if (projectId) schedule(projectId)
    },
    [projectId, generation]
  )

  return { cards, confirm, accept, dismiss, retry }
}

function useDeviceConfirmation(
  projectId: string | null,
  generation: ReturnType<typeof useWorkspaceSessionGeneration>
): DeviceProposals['confirm'] {
  const confirm = useCallback(
    async (ref: string, input: ConfirmInput): Promise<ConfirmOut | null> => {
      const card = useStore.getState().states[ref]
      if (!projectId || !current(projectId, generation) || !settled(card) || !card.proposal)
        return null
      const appearance = useStore.getState().appearances[ref]
      const body = { ...confirmBody(card.proposal, input), ...sourceOptions() }
      patch(ref, { status: 'confirming', error: null, conflictRobotId: null })
      const confirmationStart = startConfirmation()
      try {
        const result = await confirmDetected(projectId, ref, body)
        // The robot's card closes hw:confirm_to_node when it mounts (GraphCard).
        if (!currentAppearance(projectId, generation, ref, appearance)) return null
        awaitMark(result.robot.id, confirmationStart)
        if (currentAppearance(projectId, generation, ref, appearance))
          patch(ref, { status: 'done', result })
        return result
      } catch (failure) {
        if (currentAppearance(projectId, generation, ref, appearance))
          patch(ref, {
            status: 'failed',
            error: hardwareErrorText(failure),
            conflictRobotId: conflictRobotId(failure)
          })
        return null
      }
    },
    [projectId, generation]
  )

  return confirm
}
