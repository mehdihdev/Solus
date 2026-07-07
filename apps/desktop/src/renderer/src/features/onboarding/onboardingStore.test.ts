import { describe, it, expect, beforeEach } from 'vitest'
import {
  useOnboardingStore,
  connectedCount,
  canBuildModel,
  type ConnectionState
} from './onboardingStore'
import { INTEGRATIONS } from './integrations.constants'

describe('onboarding selectors', () => {
  it('connectedCount counts only done sources', () => {
    const conns: Record<string, ConnectionState> = {
      github: { phase: 'done' },
      kicad: { phase: 'busy', stepIdx: 1 },
      onshape: { phase: 'done' }
    }
    expect(connectedCount(conns)).toBe(2)
  })

  it('canBuildModel needs at least two connected', () => {
    expect(canBuildModel({ github: { phase: 'done' } })).toBe(false)
    expect(canBuildModel({ github: { phase: 'done' }, ros: { phase: 'done' } })).toBe(true)
  })
})

describe('onboardingStore', () => {
  beforeEach(() => {
    useOnboardingStore.getState().reset()
  })

  it('starts on the About step with the connect path', () => {
    const s = useOnboardingStore.getState()
    expect(s.step).toBe(0)
    expect(s.path).toBe('connect')
    expect(s.buildDone).toBe(false)
  })

  it('walks a source through busy → done', () => {
    const store = useOnboardingStore.getState()
    store.beginConnect('github')
    expect(useOnboardingStore.getState().connections.github).toEqual({ phase: 'busy', stepIdx: 0 })
    store.setConnectStep('github', 2)
    expect(useOnboardingStore.getState().connections.github).toEqual({ phase: 'busy', stepIdx: 2 })
    store.completeConnect('github')
    expect(useOnboardingStore.getState().connections.github).toEqual({ phase: 'done' })
  })

  it('setConnection replaces a source state wholesale (real github flow)', () => {
    const store = useOnboardingStore.getState()
    store.setConnection('github', {
      phase: 'busy',
      stepIdx: 0,
      label: 'Authorizing…',
      sourceId: 's1'
    })
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'busy',
      stepIdx: 0,
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

  it('failConnect marks a source errored and keeps it out of the connected count', () => {
    const store = useOnboardingStore.getState()
    store.completeConnect('kicad')
    store.failConnect('github', 'GitHub sign-in was cancelled.')
    const conns = useOnboardingStore.getState().connections
    expect(conns.github).toEqual({ phase: 'error', error: 'GitHub sign-in was cancelled.' })
    expect(connectedCount(conns)).toBe(1)
  })

  it('connectAll marks every integration done (template path)', () => {
    useOnboardingStore.getState().connectAll()
    const conns = useOnboardingStore.getState().connections
    expect(connectedCount(conns)).toBe(INTEGRATIONS.length)
  })

  it('accumulates build log lines and finishes', () => {
    const store = useOnboardingStore.getState()
    store.appendBuildLine(['Indexing strider-fw', '214 files'])
    store.appendBuildLine(['Resolving links', '31 links'])
    expect(useOnboardingStore.getState().buildLog).toHaveLength(2)
    store.finishBuild()
    expect(useOnboardingStore.getState().buildDone).toBe(true)
  })

  it('reset returns to the initial state', () => {
    const store = useOnboardingStore.getState()
    store.setStep(2)
    store.setDescription('a quadruped')
    store.connectAll()
    store.reset()
    const s = useOnboardingStore.getState()
    expect(s.step).toBe(0)
    expect(s.description).toBe('')
    expect(connectedCount(s.connections)).toBe(0)
  })
})


describe('resetBuild', () => {
  it('clears the build log and done flag without touching other state', () => {
    const store = useOnboardingStore.getState()
    store.setDescription('keep me')
    store.appendBuildLine(['a', 'b'])
    store.finishBuild()
    useOnboardingStore.getState().resetBuild()
    const s = useOnboardingStore.getState()
    expect(s.buildLog).toEqual([])
    expect(s.buildDone).toBe(false)
    expect(s.description).toBe('keep me')
  })
})
