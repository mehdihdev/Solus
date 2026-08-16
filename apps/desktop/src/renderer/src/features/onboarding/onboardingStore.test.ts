import { describe, it, expect, beforeEach } from 'vitest'
import {
  useOnboardingStore,
  connectedCount,
  canBuildModel,
  type BuildLine,
  type ConnectionState
} from './onboardingStore'

describe('onboarding selectors', () => {
  it('connectedCount counts only done sources', () => {
    const conns: Record<string, ConnectionState> = {
      github: { phase: 'done' },
      kicad: { phase: 'busy', label: 'Parsing netlist…' },
      altium: { phase: 'done' }
    }
    expect(connectedCount(conns)).toBe(2)
  })

  it('canBuildModel needs at least two connected', () => {
    expect(canBuildModel({ github: { phase: 'done' } })).toBe(false)
    expect(canBuildModel({ github: { phase: 'done' }, kicad: { phase: 'done' } })).toBe(true)
  })
})

describe('onboardingStore', () => {
  beforeEach(() => {
    useOnboardingStore.getState().reset()
  })

  it('starts on the About step with nothing connected or built', () => {
    const s = useOnboardingStore.getState()
    expect(s.step).toBe(0)
    expect(s.connections).toEqual({})
    expect(s.buildLog).toEqual([])
    expect(s.buildDone).toBe(false)
    expect(s.buildEntityCount).toBeNull()
  })

  it('setConnection walks a source through the real busy → done states', () => {
    const store = useOnboardingStore.getState()
    store.setConnection('github', {
      phase: 'busy',
      label: 'Authorizing…',
      sourceId: 's1'
    })
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'busy',
      label: 'Authorizing…',
      sourceId: 's1'
    })
    store.setConnection('github', {
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 214 entities indexed'
    })
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 214 entities indexed'
    })
  })

  it('setConnection carries the machine-readable stage for the wizard step rail', () => {
    const store = useOnboardingStore.getState()
    store.setConnection('github', { phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    const state = useOnboardingStore.getState().connections.github
    expect(state).toEqual({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
  })

  it('clearConnection removes only the named source, back to "not started"', () => {
    const store = useOnboardingStore.getState()
    store.setConnection('github', { phase: 'busy', label: 'Authorizing…' })
    store.setConnection('kicad', { phase: 'done' })
    store.clearConnection('github')
    const conns = useOnboardingStore.getState().connections
    expect(conns.github).toBeUndefined()
    expect(conns.kicad).toEqual({ phase: 'done' })
  })

  it('failConnect marks a source errored and keeps it out of the connected count', () => {
    const store = useOnboardingStore.getState()
    store.setConnection('kicad', { phase: 'done' })
    store.failConnect('github', 'GitHub sign-in was cancelled.')
    const conns = useOnboardingStore.getState().connections
    expect(conns.github).toEqual({ phase: 'error', error: 'GitHub sign-in was cancelled.' })
    expect(connectedCount(conns)).toBe(1)
  })

  it('setBuildLog replaces the real sync lines wholesale', () => {
    const store = useOnboardingStore.getState()
    const first: BuildLine[] = [{ name: 'strider-fw', detail: 'checking sync…', state: 'pending' }]
    store.setBuildLog(first)
    expect(useOnboardingStore.getState().buildLog).toEqual(first)
    const second: BuildLine[] = [
      { name: 'strider-fw', detail: '214 entities · 12 relations', state: 'ok' }
    ]
    store.setBuildLog(second)
    expect(useOnboardingStore.getState().buildLog).toEqual(second)
  })

  it('finishBuild records the real entity count when one is known', () => {
    useOnboardingStore.getState().finishBuild(12)
    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(useOnboardingStore.getState().buildEntityCount).toBe(12)
  })

  it('finishBuild without a count leaves the count unknown, never fabricated', () => {
    useOnboardingStore.getState().finishBuild()
    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(useOnboardingStore.getState().buildEntityCount).toBeNull()
  })

  it('reset returns to the initial state', () => {
    const store = useOnboardingStore.getState()
    store.setStep(2)
    store.setDescription('a quadruped')
    store.setConnection('github', { phase: 'done' })
    store.finishBuild(5)
    store.reset()
    const s = useOnboardingStore.getState()
    expect(s.step).toBe(0)
    expect(s.description).toBe('')
    expect(connectedCount(s.connections)).toBe(0)
    expect(s.buildDone).toBe(false)
    expect(s.buildEntityCount).toBeNull()
  })
})

describe('resetBuild', () => {
  it('clears the build log, done flag and entity count without touching other state', () => {
    const store = useOnboardingStore.getState()
    store.setDescription('keep me')
    store.setBuildLog([{ name: 'a', detail: 'b', state: 'ok' }])
    store.finishBuild(7)
    useOnboardingStore.getState().resetBuild()
    const s = useOnboardingStore.getState()
    expect(s.buildLog).toEqual([])
    expect(s.buildDone).toBe(false)
    expect(s.buildEntityCount).toBeNull()
    expect(s.description).toBe('keep me')
  })
})
