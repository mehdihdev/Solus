import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '../../store/authStore'
import {
  askSolAbout,
  chatKey,
  PINNED_CONTEXT_STORAGE_KEY,
  selectPins,
  takeDraft,
  usePinnedContextStore
} from './pinnedContextStore'
import { useSolSessionStore } from './solSessionStore'

const imu = { id: 'e1', name: 'IMU', domain: 'electrical', type: 'sensor' }
const motor = { id: 'e2', name: 'Motor', domain: 'mechanical', type: 'actuator' }

beforeEach(() => {
  localStorage.clear()
  usePinnedContextStore.getState().resetForSignOut()
  useSolSessionStore.setState({ conversationByProject: {} })
})

describe('pinnedContextStore', () => {
  it('pins once per node, unpins, clears, and selects per chat', () => {
    const key = chatKey('p1', 'c1')
    const store = usePinnedContextStore.getState()
    store.pin(key, imu)
    store.pin(key, imu)
    store.pin(key, motor)
    expect(selectPins(usePinnedContextStore.getState(), 'p1', 'c1').map((p) => p.id)).toEqual([
      'e1',
      'e2'
    ])
    expect(selectPins(usePinnedContextStore.getState(), 'p1', 'other')).toEqual([])
    expect(selectPins(usePinnedContextStore.getState(), null, 'c1')).toEqual([])
    store.unpin(key, 'e1')
    expect(selectPins(usePinnedContextStore.getState(), 'p1', 'c1').map((p) => p.id)).toEqual([
      'e2'
    ])
    store.clear(key)
    expect(selectPins(usePinnedContextStore.getState(), 'p1', 'c1')).toEqual([])
  })

  it('moves a fresh chat’s pins onto the conversation the first send created', () => {
    const store = usePinnedContextStore.getState()
    store.pin(chatKey('p1', null), imu)
    store.pin(chatKey('p1', 'c9'), motor)
    store.adoptConversation('p1', 'c9')
    const state = usePinnedContextStore.getState()
    expect(selectPins(state, 'p1', null)).toEqual([])
    expect(selectPins(state, 'p1', 'c9').map((p) => p.id)).toEqual(['e2', 'e1'])
  })

  it('askSolAbout pins to the active chat and seeds a one-shot draft', () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    askSolAbout('p1', imu)
    expect(selectPins(usePinnedContextStore.getState(), 'p1', 'c1').map((p) => p.name)).toEqual([
      'IMU'
    ])
    expect(takeDraft()).toBe('About IMU: ')
    expect(takeDraft()).toBeNull()
  })

  it('persists the pins (not the draft) and forgets everything when the account ends', () => {
    usePinnedContextStore.getState().pin(chatKey('p1', 'c1'), imu)
    usePinnedContextStore.getState().setDraft('x')
    const stored = JSON.parse(localStorage.getItem(PINNED_CONTEXT_STORAGE_KEY) ?? '{}') as {
      state?: { pinsByChat?: unknown; draft?: unknown }
    }
    expect(stored.state?.pinsByChat).toEqual({ 'p1:c1': [imu] })
    expect(stored.state?.draft).toBeUndefined()
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.com' } })
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(usePinnedContextStore.getState().pinsByChat).toEqual({})
    expect(usePinnedContextStore.getState().draft).toBeNull()
  })
})
