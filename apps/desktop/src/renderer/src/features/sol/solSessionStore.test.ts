// SOLUSDEV-252 S3: the non-orb SOL session state — per-project conversation,
// the streaming flag. Conversations persist (the SOL window is a separate
// renderer and rehydrates from the same localStorage); streaming never does.
import { describe, it, expect, beforeEach } from 'vitest'
import {
  useSolSessionStore,
  SOL_SESSION_STORAGE_KEY,
  LEGACY_ORB_STORAGE_KEY,
  readLegacyConversations,
  selectConversationId
} from './solSessionStore'
import { useAuthStore } from '../../store/authStore'

beforeEach(() => {
  localStorage.clear()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
})

describe('solSessionStore transitions', () => {
  it('records the active conversation per project immutably', () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    const before = useSolSessionStore.getState().conversationByProject
    useSolSessionStore.getState().setConversation('p2', 'c2')
    const after = useSolSessionStore.getState().conversationByProject
    expect(after).not.toBe(before)
    expect(after).toEqual({ p1: 'c1', p2: 'c2' })
  })

  it('forgets only the given project’s conversation', () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useSolSessionStore.getState().setConversation('p2', 'c2')
    useSolSessionStore.getState().clearConversation('p1')
    expect(useSolSessionStore.getState().conversationByProject).toEqual({ p2: 'c2' })
  })

  it('selectConversationId scopes by project and degrades to null', () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    const s = useSolSessionStore.getState()
    expect(selectConversationId(s, 'p1')).toBe('c1')
    expect(selectConversationId(s, 'p2')).toBeNull()
    expect(selectConversationId(s, null)).toBeNull()
  })
})

describe('solSessionStore persistence', () => {
  it('persists conversations under the new key but never the streaming flag', () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useSolSessionStore.getState().setStreaming(true)
    const raw = localStorage.getItem(SOL_SESSION_STORAGE_KEY)
    expect(raw).not.toBeNull()
    const persisted = (JSON.parse(raw as string) as { state: Record<string, unknown> }).state
    expect(persisted.conversationByProject).toEqual({ p1: 'c1' })
    expect(persisted).not.toHaveProperty('streaming')
  })

  it('reads the legacy orb store’s conversation map once (ponytail: drop after one release)', () => {
    localStorage.setItem(
      LEGACY_ORB_STORAGE_KEY,
      JSON.stringify({ state: { corner: 'br', conversationByProject: { p1: 'c9' } }, version: 0 })
    )
    expect(readLegacyConversations(localStorage)).toEqual({ p1: 'c9' })
    // Malformed or absent legacy data is simply nothing to migrate.
    localStorage.setItem(LEGACY_ORB_STORAGE_KEY, '{not json')
    expect(readLegacyConversations(localStorage)).toBeNull()
    localStorage.setItem(LEGACY_ORB_STORAGE_KEY, JSON.stringify({ state: { x: 1 } }))
    expect(readLegacyConversations(localStorage)).toBeNull()
    localStorage.removeItem(LEGACY_ORB_STORAGE_KEY)
    expect(readLegacyConversations(localStorage)).toBeNull()
  })
})

describe('sign-out (SEC-M4)', () => {
  it('clears per-account conversation ids so a new token never reuses them', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useSolSessionStore.getState().setStreaming(true)
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(useSolSessionStore.getState().conversationByProject).toEqual({})
    expect(useSolSessionStore.getState().streaming).toBe(false)
  })

  it('also resets on an in-place identity swap', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useAuthStore.setState({ status: 'authenticated', user: { email: 'other@b.dev' } })
    expect(useSolSessionStore.getState().conversationByProject).toEqual({})
  })
})
