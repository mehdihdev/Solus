// SOLX-02: orb state — dock corner, expand/collapse, detach, per-project
// conversation, streaming pulse. Dock/expand/conversation prefs persist
// (the detached #/orb window is a separate renderer and rehydrates from the
// same localStorage); runtime flags (streaming, detached) never persist.
import { describe, it, expect, beforeEach } from 'vitest'
import {
  useOrbStore,
  ORB_STORAGE_KEY,
  selectOrbPulse,
  selectConversationId,
  type OrbCorner
} from './orbStore'

beforeEach(() => {
  localStorage.clear()
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
})

describe('orbStore transitions', () => {
  it('starts docked bottom-right, collapsed, attached, not streaming', () => {
    const s = useOrbStore.getState()
    expect(s.corner).toBe('br')
    expect(s.expanded).toBe(false)
    expect(s.detached).toBe(false)
    expect(s.streaming).toBe(false)
    expect(s.conversationByProject).toEqual({})
  })

  it('docks to any corner', () => {
    for (const corner of ['tl', 'tr', 'bl', 'br'] as OrbCorner[]) {
      useOrbStore.getState().setCorner(corner)
      expect(useOrbStore.getState().corner).toBe(corner)
    }
  })

  it('toggles and sets the expanded panel', () => {
    useOrbStore.getState().toggleExpanded()
    expect(useOrbStore.getState().expanded).toBe(true)
    useOrbStore.getState().toggleExpanded()
    expect(useOrbStore.getState().expanded).toBe(false)
    useOrbStore.getState().setExpanded(true)
    expect(useOrbStore.getState().expanded).toBe(true)
  })

  it('tracks detached and streaming flags', () => {
    useOrbStore.getState().setDetached(true)
    useOrbStore.getState().setStreaming(true)
    expect(useOrbStore.getState().detached).toBe(true)
    expect(useOrbStore.getState().streaming).toBe(true)
  })

  it('records the active conversation per project immutably', () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    const before = useOrbStore.getState().conversationByProject
    useOrbStore.getState().setConversation('p2', 'c2')
    const after = useOrbStore.getState().conversationByProject
    expect(after).not.toBe(before)
    expect(before).toEqual({ p1: 'c1' })
    expect(after).toEqual({ p1: 'c1', p2: 'c2' })
  })
})

describe('orbStore pure selectors', () => {
  it('selectOrbPulse mirrors streaming', () => {
    expect(selectOrbPulse(useOrbStore.getState())).toBe(false)
    useOrbStore.getState().setStreaming(true)
    expect(selectOrbPulse(useOrbStore.getState())).toBe(true)
  })

  it('selectConversationId scopes by project and degrades to null', () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    const s = useOrbStore.getState()
    expect(selectConversationId(s, 'p1')).toBe('c1')
    expect(selectConversationId(s, 'p2')).toBeNull()
    expect(selectConversationId(s, null)).toBeNull()
  })
})

describe('orbStore persistence', () => {
  it('persists dock/expand/conversation prefs but never runtime flags', () => {
    const st = useOrbStore.getState()
    st.setCorner('tl')
    st.setExpanded(true)
    st.setConversation('p1', 'c1')
    st.setDetached(true)
    st.setStreaming(true)
    const raw = localStorage.getItem(ORB_STORAGE_KEY)
    expect(raw).not.toBeNull()
    const persisted = (JSON.parse(raw as string) as { state: Record<string, unknown> }).state
    expect(persisted.corner).toBe('tl')
    expect(persisted.expanded).toBe(true)
    expect(persisted.conversationByProject).toEqual({ p1: 'c1' })
    expect(persisted).not.toHaveProperty('streaming')
    expect(persisted).not.toHaveProperty('detached')
  })
})

describe('sign-out (SOLX-02 Phase-4 security)', () => {
  it('clears per-account conversation ids so a new token never reuses them', () => {
    // SEC-M4: persisted ids are per-account.
    useOrbStore.getState().setConversation('p1', 'c1')
    useOrbStore.getState().setExpanded(true)
    useOrbStore.getState().resetForSignOut()
    expect(useOrbStore.getState().conversationByProject).toEqual({})
    expect(useOrbStore.getState().expanded).toBe(false)
  })
})
