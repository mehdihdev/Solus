// SOLUSDEV-321 P1-T6: how the store keeps a turn's context manifest — on the session, and the glow
// it lights on the graph. Pure: a fake patcher stands in for the store, so no network, no
// component. (The frames that land on the assistant item are tested in solChatItems.test.ts.)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { HIGHLIGHT_TTL_MS, useFocusStore } from '../workspace/focusStore'
import { applyContextUsed } from './contextUsed'
import type { SolSession } from './solChatStore'
import type { SolStreamEvent } from './solStream'

const FOCUSED = '0f9c2f2a-1111-4222-8333-444455556666'
const NAMED = '0f9c2f2a-1111-4222-8333-444455557777'

type ContextUsedEvent = Extract<SolStreamEvent, { type: 'context_used' }>
const MANIFEST: ContextUsedEvent = {
  type: 'context_used',
  sections: [{ kind: 'graph', citation: '[graph:motor_driver]', tokens: 120, layer: 'graph' }],
  truncated: false,
  dropped: 0,
  layers: [
    { layer: 'graph', tokens: 120, emptyReason: null },
    { layer: 'screen', tokens: 0, emptyReason: 'no screenshot on this turn' }
  ],
  anchors: [
    { id: FOCUSED, reason: 'focused' },
    { id: NAMED, reason: 'name_match' }
  ],
  anchorsDropped: [
    { id: '0f9c2f2a-1111-4222-8333-444455558888', reason: 'pinned', cause: 'over_cap' }
  ]
}

const EMPTY: SolSession = {
  conversationId: null,
  items: [],
  contextUsed: null,
  creditsExhausted: false,
  streaming: false,
  status: 'ready'
}

/** A one-session stand-in for the store's `patchSession`, remembering whose session it touched. */
function sessionPatcher(): {
  patchSession: Parameters<typeof applyContextUsed>[0]
  session: () => SolSession
  touched: string[]
} {
  let session = EMPTY
  const touched: string[] = []
  return {
    patchSession: (projectId, fn) => {
      touched.push(projectId)
      session = fn(session)
    },
    session: () => session,
    touched
  }
}

// Project p1 is the one open on screen — the one whose graph can glow. Writing the persisted
// workspace store makes jsdom's localStorage schedule a timer of its own, so the fake clock is
// emptied after every such write: `getTimerCount()` then counts only the glow's timer.
beforeEach(() => {
  vi.useFakeTimers()
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' } })
  vi.clearAllTimers()
})
afterEach(() => {
  useFocusStore.getState().reset()
  useWorkspaceStore.getState().reset()
  vi.useRealTimers()
})

describe('applyContextUsed', () => {
  it('lands the whole manifest on the session of the turn’s project', () => {
    const { patchSession, session, touched } = sessionPatcher()
    applyContextUsed(patchSession, 'p1', MANIFEST)
    expect(touched).toEqual(['p1'])
    expect(session().contextUsed).toEqual({
      sections: MANIFEST.sections,
      truncated: false,
      dropped: 0,
      layers: MANIFEST.layers,
      anchors: MANIFEST.anchors,
      anchorsDropped: MANIFEST.anchorsDropped
    })
    // The frame's own `type` is not part of the manifest the panel reads.
    expect(session().contextUsed).not.toHaveProperty('type')
  })

  it('glows the anchored entities for the whole window, then lets go', () => {
    applyContextUsed(sessionPatcher().patchSession, 'p1', MANIFEST)
    expect(useFocusStore.getState().highlightedIds).toEqual([FOCUSED, NAMED])
    vi.advanceTimersByTime(HIGHLIGHT_TTL_MS - 1)
    expect(useFocusStore.getState().highlightedIds).toEqual([FOCUSED, NAMED])
    vi.advanceTimersByTime(1)
    expect(useFocusStore.getState().highlightedIds).toEqual([])
  })

  it('a turn with no anchors puts out the last turn’s glow instead of keeping it', () => {
    applyContextUsed(sessionPatcher().patchSession, 'p1', MANIFEST)
    applyContextUsed(sessionPatcher().patchSession, 'p1', { ...MANIFEST, anchors: [] })
    expect(useFocusStore.getState().highlightedIds).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('a frame written before the anchors existed glows nothing and keeps the fields absent', () => {
    const older: ContextUsedEvent = {
      type: 'context_used',
      sections: [],
      truncated: false,
      dropped: 0
    }
    const { patchSession, session } = sessionPatcher()
    expect(() => applyContextUsed(patchSession, 'p1', older)).not.toThrow()
    expect(useFocusStore.getState().highlightedIds).toEqual([])
    expect(session().contextUsed?.anchors).toBeUndefined()
    expect(session().contextUsed?.layers).toBeUndefined()
  })

  // Sessions outlive navigation: a turn can still be streaming for project A while B is open. A's
  // ids match no card of B's graph, but its call would still replace or clear B's live glow — the
  // store has one global timer.
  it('a turn streaming for another project neither lights nor puts out the open project’s glow', () => {
    useFocusStore.getState().highlight([FOCUSED], HIGHLIGHT_TTL_MS)
    const other = sessionPatcher()
    applyContextUsed(other.patchSession, 'p2', MANIFEST)
    expect(useFocusStore.getState().highlightedIds).toEqual([FOCUSED])
    applyContextUsed(other.patchSession, 'p2', { ...MANIFEST, anchors: [] })
    expect(useFocusStore.getState().highlightedIds).toEqual([FOCUSED])
    // The manifest still lands on THAT project's session: only the glow is the open project's.
    expect(other.touched).toEqual(['p2', 'p2'])
    expect(other.session().contextUsed?.anchors).toEqual([])
  })

  it('glows nothing while no project is open', () => {
    useWorkspaceStore.getState().reset()
    vi.clearAllTimers()
    applyContextUsed(sessionPatcher().patchSession, 'p1', MANIFEST)
    expect(useFocusStore.getState().highlightedIds).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })
})
