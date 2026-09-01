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

describe('background completion + away toast', () => {
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
        version: 1,
        items: [
          { id: 't1', role: 'user', content: 'old question' },
          { id: 't2', role: 'assistant', content: 'old answer' }
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
      JSON.stringify({ version: 1, items: [{ id: 'stale', role: 'user', content: 'stale' }] })
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
