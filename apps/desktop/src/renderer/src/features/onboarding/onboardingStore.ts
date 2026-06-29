// Onboarding flow state machine. Mirrors the three-step flow in
// TestDesign/app/onboarding.jsx (About → Connect → Build). Connection and build
// are simulated in this prototype slice; the timed animations live in the
// component and drive these pure transitions.
import { create } from 'zustand'
import { INTEGRATIONS, MIN_SOURCES_TO_BUILD } from './integrations.constants'

export type OnboardingStep = 0 | 1 | 2
export type StartingPoint = 'connect' | 'template'

export type ConnectionState = { phase: 'busy'; stepIdx: number } | { phase: 'done' }

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
  connectAll: () => void
  appendBuildLine: (line: BuildLine) => void
  finishBuild: () => void
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

  connectAll: () =>
    set(() => ({
      connections: Object.fromEntries(INTEGRATIONS.map((i) => [i.id, { phase: 'done' as const }]))
    })),

  appendBuildLine: (line) => set((s) => ({ buildLog: [...s.buildLog, line] })),
  finishBuild: () => set({ buildDone: true }),
  reset: () => set({ ...INITIAL, connections: {}, buildLog: [] })
}))
