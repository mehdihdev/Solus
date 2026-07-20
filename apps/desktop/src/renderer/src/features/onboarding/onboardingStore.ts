// Onboarding flow state machine (About → Connect → Build). Every state here is
// driven by REAL flows only (SOLUSDEV-152 de-simulation): connections carry the
// live connector progress, and the build log mirrors actual source syncs.
import { create } from 'zustand'
import type { GithubRepo } from '../../lib/api/resources'
import { MIN_SOURCES_TO_BUILD } from './integrations.constants'

export type OnboardingStep = 0 | 1 | 2

/**
 * Per-source connection state, fed by the real connectors (GitHub OAuth,
 * committed-export EDA): a live `label` for progress copy, the `sourceId` once
 * one exists, discovered `repos` when a picker is needed, and a real `result`
 * string on completion. `error` is reachable via OAuth cancel, sync failure,
 * missing Electron bridge, or an unlinked workspace.
 */
export type ConnectionState =
  | { phase: 'busy'; label?: string; sourceId?: string; repos?: GithubRepo[] }
  | { phase: 'done'; sourceId?: string; result?: string }
  | { phase: 'error'; error: string; sourceId?: string }

export type BuildLineState = 'pending' | 'ok' | 'failed' | 'idle'

/** One real source's sync status shown on the Build step. */
export interface BuildLine {
  readonly name: string
  readonly detail: string
  readonly state: BuildLineState
}

export interface OnboardingState {
  step: OnboardingStep
  description: string
  connections: Record<string, ConnectionState>
  buildLog: readonly BuildLine[]
  buildDone: boolean
  /** Real entity count from the graph after the build, or null if unknown. */
  buildEntityCount: number | null

  setStep: (step: OnboardingStep) => void
  setDescription: (description: string) => void
  /** Replace a source's connection state wholesale (real-connect flow). */
  setConnection: (id: string, state: ConnectionState) => void
  /** Mark a source's connect attempt as failed with a message. */
  failConnect: (id: string, error: string) => void
  /** Replace the build log with the latest real sync lines. */
  setBuildLog: (lines: readonly BuildLine[]) => void
  finishBuild: (entityCount?: number) => void
  /** Restart the build progress state (used when the Build step (re)mounts). */
  resetBuild: () => void
  reset: () => void
}

/** Count of fully-connected sources. Pure + testable. */
export function connectedCount(connections: Record<string, ConnectionState>): number {
  return Object.values(connections).filter((c) => c.phase === 'done').length
}

/** Whether enough sources are connected to build the context model. */
export function canBuildModel(connections: Record<string, ConnectionState>): boolean {
  return connectedCount(connections) >= MIN_SOURCES_TO_BUILD
}

const INITIAL = {
  step: 0 as OnboardingStep,
  description: '',
  connections: {} as Record<string, ConnectionState>,
  buildLog: [] as readonly BuildLine[],
  buildDone: false,
  buildEntityCount: null as number | null
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  ...INITIAL,

  setStep: (step) => set({ step }),
  setDescription: (description) => set({ description }),

  setConnection: (id, state) => set((s) => ({ connections: { ...s.connections, [id]: state } })),

  failConnect: (id, error) =>
    set((s) => ({ connections: { ...s.connections, [id]: { phase: 'error', error } } })),

  setBuildLog: (lines) => set({ buildLog: lines }),
  finishBuild: (entityCount) => set({ buildDone: true, buildEntityCount: entityCount ?? null }),
  resetBuild: () => set({ buildLog: [], buildDone: false, buildEntityCount: null }),
  reset: () => set({ ...INITIAL, connections: {}, buildLog: [] })
}))
