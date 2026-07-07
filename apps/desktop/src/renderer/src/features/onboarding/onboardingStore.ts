// Onboarding flow state machine. Mirrors the three-step flow in
// TestDesign/app/onboarding.jsx (About → Connect → Build). Connection and build
// are simulated in this prototype slice; the timed animations live in the
// component and drive these pure transitions.
import { create } from 'zustand'
import type { GithubRepo } from '../../lib/api/resources'
import { INTEGRATIONS, MIN_SOURCES_TO_BUILD } from './integrations.constants'

export type OnboardingStep = 0 | 1 | 2
export type StartingPoint = 'connect' | 'template'

/**
 * Per-source connection state. The simulated connectors only ever use
 * `stepIdx`; the real GitHub connector also carries its `sourceId`, the
 * discovered `repos` (when a repo picker is needed), a real `result` string,
 * and a `label` override for live progress copy. The `error` phase is new and
 * reachable only by the real flow (OAuth cancel, sync failure, no Electron).
 */
export type ConnectionState =
  | { phase: 'busy'; stepIdx: number; label?: string; sourceId?: string; repos?: GithubRepo[] }
  | { phase: 'done'; sourceId?: string; result?: string }
  | { phase: 'error'; error: string; sourceId?: string }

export type BuildLine = readonly [string, string]

export interface OnboardingState {
  step: OnboardingStep
  description: string
  path: StartingPoint
  templateId: string | null
  connections: Record<string, ConnectionState>
  buildLog: BuildLine[]
  buildDone: boolean

  setStep: (step: OnboardingStep) => void
  setDescription: (description: string) => void
  setPath: (path: StartingPoint) => void
  setTemplate: (templateId: string) => void
  beginConnect: (id: string) => void
  setConnectStep: (id: string, stepIdx: number) => void
  completeConnect: (id: string) => void
  /** Replace a source's connection state wholesale (real-connect flow). */
  setConnection: (id: string, state: ConnectionState) => void
  /** Mark a source's connect attempt as failed with a message. */
  failConnect: (id: string, error: string) => void
  connectAll: () => void
  appendBuildLine: (line: BuildLine) => void
  finishBuild: () => void
  /** Restart the build animation state (used when the Build step (re)mounts). */
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
  path: 'connect' as StartingPoint,
  templateId: null,
  connections: {} as Record<string, ConnectionState>,
  buildLog: [] as BuildLine[],
  buildDone: false
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  ...INITIAL,

  setStep: (step) => set({ step }),
  setDescription: (description) => set({ description }),
  setPath: (path) => set({ path }),
  setTemplate: (templateId) => set({ templateId }),

  beginConnect: (id) =>
    set((s) => ({ connections: { ...s.connections, [id]: { phase: 'busy', stepIdx: 0 } } })),

  setConnectStep: (id, stepIdx) =>
    set((s) => ({ connections: { ...s.connections, [id]: { phase: 'busy', stepIdx } } })),

  completeConnect: (id) =>
    set((s) => ({ connections: { ...s.connections, [id]: { phase: 'done' } } })),

  setConnection: (id, state) => set((s) => ({ connections: { ...s.connections, [id]: state } })),

  failConnect: (id, error) =>
    set((s) => ({ connections: { ...s.connections, [id]: { phase: 'error', error } } })),

  connectAll: () =>
    set(() => ({
      connections: Object.fromEntries(INTEGRATIONS.map((i) => [i.id, { phase: 'done' as const }]))
    })),

  appendBuildLine: (line) => set((s) => ({ buildLog: [...s.buildLog, line] })),
  finishBuild: () => set({ buildDone: true }),
  resetBuild: () => set({ buildLog: [], buildDone: false }),
  reset: () => set({ ...INITIAL, connections: {}, buildLog: [] })
}))
