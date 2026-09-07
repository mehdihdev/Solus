// SOLUSDEV-233: SOL chat sessions outlive the page — background completion,
// the away toast, and sign-out teardown.
import { act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import type { SolStreamEvent } from './solStream'
import { useAuthStore } from '../../store/authStore'
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useOrbStore } from './orbStore'
import {
  resetSolChatSessions,
  selectSession,
  sendMessage,
  syncSession,
  useSolChatStore
} from './solChatStore'

vi.mock('../preferences/preferencesStore', () => ({
  preferencesForTurn: vi.fn(async () => ({
    schema_version: 1,
    freeText: '',
    codeStyle: '',
    mechanical: '',
    electrical: 'XT30 for power.',
    documentation: '',
    unitsStandards: ''
  }))
}))
vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

function messageEvent(content: string): SolStreamEvent {
  return { type: 'message', role: 'assistant', content, citations: [] }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
})

describe('engineering preferences ride along (SOLUSDEV-244)', () => {
  it('passes the loaded document to every turn', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => onEvent(messageEvent('ok')))
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        preferences: expect.objectContaining({ electrical: 'XT30 for power.' })
      })
    )
  })
})

describe('background completion + away toast', () => {
  it('names the fact, not the prompt, when the reply lands under another project (SOLUSDEV-242)', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('sol')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      // The user switches to Arm while Rover's turn is still streaming.
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'Arm' } })
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'why is joint 2 stalling?', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast?.title).toBe('SOL replied')
    expect(toast?.body).not.toContain('joint 2')
    expect(toast?.action).toBeUndefined()
  })

  it('raises the shell toast when a reply completes while the user is away', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('home') // not on the SOL page
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'why is joint 2 stalling?', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast).not.toBeNull()
    expect(toast?.kind).toBe('ok')
    expect(toast?.title).toBe('SOL replied')
    expect(toast?.body).toContain('why is joint 2 stalling?')
    // The workspace is still on the turn's project, so View jumps to SOL.
    expect(toast?.action).toBe('View')
    expect(toast?.screen).toBe('sol')
  })

  it('stays quiet when the user is watching the SOL page', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('sol')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    expect(useShellStore.getState().toast).toBeNull()
  })

  it('warns (without a raw error) when a backgrounded turn fails', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    useShellStore.getState().setLastMain('home')
    streamSolMessage.mockRejectedValue(new Error('ECONNREFUSED'))
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast?.kind).toBe('warn')
    expect(toast?.title).toBe('SOL turn failed')
    expect(JSON.stringify(toast)).not.toContain('ECONNREFUSED')
  })

  it('the finished reply waits in the session for the next mount', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    let finish: () => void = () => undefined
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      await new Promise<void>((resolve) => {
        finish = () => {
          onEvent(messageEvent('Done in the background.'))
          resolve()
        }
      })
    })
    const pending = sendMessage('p1', 'hello', 'guide')
    expect(selectSession(useSolChatStore.getState(), 'p1').streaming).toBe(true)
    // The turn first collects the user's preferences (SOLUSDEV-244), so the
    // stream opens one tick later than the call.
    await vi.waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    await act(async () => {
      finish()
      await pending
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.streaming).toBe(false)
    expect(session.items.at(-1)?.content).toBe('Done in the background.')
  })
})

describe('sign-out teardown (SEC-M4)', () => {
  it('aborts every live stream and drops every session', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    let seen: AbortSignal | undefined
    streamSolMessage.mockImplementation(async ({ signal }) => {
      seen = signal
      await new Promise(() => undefined) // never resolves on its own
    })
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    void sendMessage('p1', 'hello', 'guide')
    await act(async () => {
      await Promise.resolve()
    })
    expect(seen?.aborted).toBe(false)

    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(seen?.aborted).toBe(true)
    expect(useSolChatStore.getState().sessions).toEqual({})
    expect(useOrbStore.getState().streaming).toBe(false)
  })
})

describe('~/.solus cache (ADR-034 Layer 1)', () => {
  const cacheRead = vi.fn()
  const cacheWrite = vi.fn().mockResolvedValue({ ok: true })
  const cacheRemove = vi.fn().mockResolvedValue({ ok: true })

  beforeEach(() => {
    cacheRead.mockReset()
    cacheWrite.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = {
      solChat: { read: cacheRead, write: cacheWrite, remove: cacheRemove }
    }
  })
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })

  it('keeps a cached chat readable when the server cannot load it', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(
      JSON.stringify({
        schema_version: 1,
        items: [
          { role: 'user', content: 'old question' },
          { role: 'assistant', content: 'old answer' }
        ]
      })
    )
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new Error('down'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.map((m) => m.content)).toEqual(['old question', 'old answer'])
    expect(session.status).toBe('ready') // the cache IS the readable history
  })

  it('the server load wins over the cache and refreshes it', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(
      JSON.stringify({
        schema_version: 1,
        // Even an id posing as a live turn cannot survive the server load —
        // file ids are rewritten to the cache- namespace (SEC review H2).
        items: [{ id: 'local-999', role: 'user', content: 'stale' }]
      })
    )
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      {
        id: 't9',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'fresh from the server',
        attrs: {},
        created_at: ''
      }
    ])
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.map((m) => m.content)).toEqual(['fresh from the server'])
    expect(cacheWrite).toHaveBeenCalled() // refreshed with server truth
  })

  it('mirrors the transcript to the cache when a turn settles', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(null)
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('cached reply'))
    })
    await act(async () => {
      await sendMessage('p1', 'question', 'guide')
    })
    const [pid, cid, payload] = cacheWrite.mock.calls.at(-1) as [string, string, string]
    expect(pid).toBe('p1')
    expect(cid).toBe('c1')
    expect(JSON.parse(payload).items.map((m: { content: string }) => m.content)).toEqual([
      'question',
      'cached reply'
    ])
  })
})

describe('server refusals outrank the cache (SEC review H1)', () => {
  const cacheRead = vi.fn()
  const cacheWrite = vi.fn().mockResolvedValue({ ok: true })
  const cacheRemove = vi.fn().mockResolvedValue({ ok: true })
  const cacheClear = vi.fn().mockResolvedValue({ ok: true })
  const CACHED = JSON.stringify({
    schema_version: 1,
    items: [{ role: 'assistant', content: 'previous owner content' }]
  })

  beforeEach(() => {
    cacheRead.mockReset()
    cacheRemove.mockClear()
    cacheClear.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = {
      solChat: { read: cacheRead, write: cacheWrite, remove: cacheRemove, clear: cacheClear }
    }
  })
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })

  it('drops the painted cache AND the file on a 404 — never renders refused data', async () => {
    const { ApiError } = await import('../../lib/api/envelope.types')
    useOrbStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(CACHED)
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new ApiError(404, 'not_found', 'gone'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items).toEqual([])
    expect(cacheRemove).toHaveBeenCalledWith('p1', 'c1')
    // The stale conversation id is forgotten so the next send starts fresh.
    expect(useOrbStore.getState().conversationByProject).toEqual({})
  })

  it('drops the painted cache on a 403 and shows offline, not the transcript', async () => {
    const { ApiError } = await import('../../lib/api/envelope.types')
    useOrbStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(CACHED)
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new ApiError(403, 'forbidden', 'no'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items).toEqual([])
    expect(session.status).toBe('offline')
    expect(cacheRemove).toHaveBeenCalledWith('p1', 'c1')
  })

  it('an in-place identity swap tears down sessions and purges the disk cache', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    let seen: AbortSignal | undefined
    streamSolMessage.mockImplementation(async ({ signal }) => {
      seen = signal
      await new Promise(() => undefined)
    })
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@x.dev' } })
    void sendMessage('p1', 'hello', 'guide')
    await act(async () => {
      await Promise.resolve()
    })
    expect(seen?.aborted).toBe(false)

    // No 'unauthenticated' edge — the session is swapped in place (OAuth
    // loopback / magic link / another window).
    useAuthStore.setState({ status: 'authenticated', user: { email: 'b@x.dev' } })
    expect(seen?.aborted).toBe(true)
    expect(useSolChatStore.getState().sessions).toEqual({})
    expect(useOrbStore.getState().conversationByProject).toEqual({})
    expect(cacheClear).toHaveBeenCalled()
  })
})
