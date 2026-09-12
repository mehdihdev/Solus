// SOLX-02: chat state — per-project history, conversation creation on first
// send, streamed tokens folding into the pending assistant item, tool trace,
// structured citations, and the session streaming flag around a turn.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import type { SolStreamEvent } from './solStream'
import { useShellStore } from '../workspace/shellStore'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions } from './solChatStore'
import { useSolChat } from './useSolChat'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
// `decide` reaches the real HTTP client otherwise. Spread the real module so
// shared values (the ConfirmationRefused error class) are not silently
// undefined — an `instanceof` against undefined throws inside the catch.
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  decideSolConfirmation: vi.fn()
}))
const createSolConversation = vi.mocked(solApi.createSolConversation)
const listSolTurns = vi.mocked(solApi.listSolTurns)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

function turn(id: string, role: solApi.SolTurn['role'], content: string): solApi.SolTurn {
  return { id, conversation_id: 'c1', role, content, attrs: {}, created_at: '2026-08-08' }
}

/** Resolve the stream after emitting the given events. */
function streamWith(events: SolStreamEvent[]): void {
  streamSolMessage.mockImplementation(async ({ onEvent }) => {
    for (const event of events) onEvent(event)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // Sessions outlive components (SOLUSDEV-233) — reset the singleton per test.
  resetSolChatSessions()
  useShellStore.getState().reset()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
})

describe('history', () => {
  it('loads the stored conversation, oldest first', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([turn('t2', 'assistant', 'Answer'), turn('t1', 'user', 'Q')])
    const { result } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(listSolTurns).toHaveBeenCalledWith('p1', 'c1')
    expect(result.current.items.map((m) => m.content)).toEqual(['Q', 'Answer'])
  })

  it('starts empty with no stored conversation and never calls the API', async () => {
    const { result } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(listSolTurns).not.toHaveBeenCalled()
    expect(result.current.items).toEqual([])
  })

  it('degrades to offline when history cannot load', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})

describe('send', () => {
  it('creates the conversation on first send and records it per project', async () => {
    createSolConversation.mockResolvedValue({ id: 'c9' } as solApi.SolConversation)
    streamWith([{ type: 'done', conversationId: 'c9', turnId: 't1' }])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hello', 'guide')
    })
    expect(createSolConversation).toHaveBeenCalledWith('p1', 'hello')
    expect(useSolSessionStore.getState().conversationByProject).toEqual({ p1: 'c9' })
    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: 'c9', content: 'hello', actionMode: 'guide' })
    )
  })

  it('passes the chosen action mode through to the stream', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamWith([])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('flash it', 'do')
    })
    expect(streamSolMessage).toHaveBeenCalledWith(expect.objectContaining({ actionMode: 'do' }))
  })

  it('folds tokens into the pending assistant item, finalizes on message, flags streaming', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    const seenStreaming: boolean[] = []
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      seenStreaming.push(useSolSessionStore.getState().streaming)
      onEvent({ type: 'token', text: 'The ' })
      onEvent({ type: 'token', text: 'IMU.' })
      onEvent({ type: 'tool_call', callId: 'k1', tool: 'get_entity' })
      onEvent({ type: 'tool_result', callId: 'k1', ok: true, errorCode: null })
      onEvent({
        type: 'message',
        role: 'assistant',
        content: 'The IMU.',
        citations: ['entity:imu']
      })
      onEvent({ type: 'done', conversationId: 'c1', turnId: 't1' })
    })
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('why?', 'guide')
    })
    expect(seenStreaming).toEqual([true]) // pulse on while the turn streams
    expect(useSolSessionStore.getState().streaming).toBe(false) // and off after
    const [user, assistant] = result.current.items
    expect(user).toMatchObject({ role: 'user', content: 'why?' })
    expect(assistant).toMatchObject({
      role: 'assistant',
      content: 'The IMU.',
      citations: ['entity:imu'],
      pending: false,
      error: null
    })
    expect(assistant.trace).toEqual([
      { callId: 'k1', tool: 'get_entity', ok: true, errorCode: null }
    ])
  })

  it('surfaces the author-safe error frame on the assistant item', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamWith([{ type: 'error', code: 'timeout', message: 'The SOL turn timed out.' }])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.items[1]).toMatchObject({
      pending: false,
      error: 'The SOL turn timed out.'
    })
  })

  it('marks the turn failed when the transport rejects, and always clears the pulse', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamSolMessage.mockRejectedValue(new Error('ECONNREFUSED'))
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.items[1].error).toBe('SOL is unreachable right now.')
    expect(result.current.items[1].error).not.toContain('ECONNREFUSED')
    expect(useSolSessionStore.getState().streaming).toBe(false)
  })

  it('ignores empty input and sends without a project', async () => {
    const { result } = renderHook(() => useSolChat(null))
    await act(async () => {
      await result.current.send('   ', 'guide')
      await result.current.send('hello', 'guide')
    })
    expect(streamSolMessage).not.toHaveBeenCalled()
    expect(createSolConversation).not.toHaveBeenCalled()
  })
})

describe('stream lifecycle (SOLX-02 → SOLUSDEV-233: sessions outlive the page)', () => {
  it('keeps the stream running on unmount and hands the reply to the next mount', async () => {
    // SEC-H3 evolution: the singleton session store owns the stream now — an
    // unmounted page no longer aborts it (leaving the SOL page mid-response
    // used to eat the reply); sign-out teardown is pinned in solChatStore.test.
    let seen: AbortSignal | undefined
    let finish: () => void = () => undefined
    streamSolMessage.mockImplementation(async ({ signal, onEvent }) => {
      seen = signal
      await new Promise<void>((resolve) => {
        finish = () => {
          onEvent({ type: 'message', role: 'assistant', content: 'Done.', citations: [] })
          resolve()
        }
      })
    })
    listSolTurns.mockResolvedValue([])
    useSolSessionStore.getState().setConversation('p1', 'c1')

    const { result, unmount } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      void result.current.send('hello', 'guide')
    })
    unmount()
    expect(seen?.aborted).toBe(false) // the turn is still running

    await act(async () => {
      finish()
      await Promise.resolve()
    })
    // Returning to the page re-attaches to the finished transcript.
    const { result: again } = renderHook(() => useSolChat('p1'))
    expect(again.current.items.at(-1)?.content).toBe('Done.')
    expect(again.current.streaming).toBe(false)
    expect(useSolSessionStore.getState().streaming).toBe(false)
  })

  it('bounds per-turn content so a runaway stream cannot grow without limit', async () => {
    listSolTurns.mockResolvedValue([])
    useSolSessionStore.getState().setConversation('p1', 'c1')
    const flood: SolStreamEvent[] = Array.from(
      { length: 60 },
      (): SolStreamEvent => ({ type: 'token', text: 'x'.repeat(10_000) })
    )
    streamWith(flood)

    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    const assistant = result.current.items.at(-1)
    expect(assistant?.content.length).toBeLessThanOrEqual(200_000)
  })
})

describe('SOL page additions (SOLUSDEV-233)', () => {
  it('exposes the turn context manifest from the context_used frame', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamWith([
      {
        type: 'context_used',
        sections: [{ kind: 'graph', citation: '[graph:motor]', tokens: 12 }],
        truncated: false,
        dropped: 1
      },
      { type: 'done', conversationId: 'c1', turnId: 't1' }
    ])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.contextUsed).toEqual({
      sections: [{ kind: 'graph', citation: '[graph:motor]', tokens: 12 }],
      truncated: false,
      dropped: 1
    })
  })

  it('branches a 402 into the credits message and flag, and 429 into backoff', async () => {
    const { ApiError } = await import('../../lib/api/envelope.types')
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamSolMessage.mockRejectedValue(new ApiError(402, 'insufficient_credits', 'no'))
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.creditsExhausted).toBe(true)
    expect(result.current.items.at(-1)?.error).toMatch(/out of SOL credits/i)

    streamSolMessage.mockRejectedValue(new ApiError(429, 'frequency_cap', 'slow down'))
    await act(async () => {
      await result.current.send('again', 'guide')
    })
    expect(result.current.items.at(-1)?.error).toMatch(/too many SOL turns/i)
  })

  it('seeds the conversation title from the first message', async () => {
    createSolConversation.mockResolvedValue({ id: 'c9' } as solApi.SolConversation)
    streamWith([{ type: 'done', conversationId: 'c9', turnId: 't1' }])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('Why is joint 2 stalling?', 'guide')
    })
    expect(createSolConversation).toHaveBeenCalledWith('p1', 'Why is joint 2 stalling?')
  })

  it('creating a conversation mid-send never reloads away the live turn', async () => {
    createSolConversation.mockResolvedValue({ id: 'c9' } as solApi.SolConversation)
    streamWith([
      { type: 'message', role: 'assistant', content: 'Answer.', citations: [] },
      { type: 'done', conversationId: 'c9', turnId: 't1' }
    ])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hello', 'guide')
    })
    // The store now points at c9, but the just-created id must not trigger a
    // history reload that wipes the streamed items.
    expect(useSolSessionStore.getState().conversationByProject).toEqual({ p1: 'c9' })
    expect(listSolTurns).not.toHaveBeenCalled()
    expect(result.current.items.map((m) => m.content)).toEqual(['hello', 'Answer.'])
  })

  it('selectConversation reloads history for the chosen chat', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([turn('t1', 'user', 'old')])
    const { result } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    listSolTurns.mockResolvedValue([turn('t9', 'user', 'other chat')])
    act(() => result.current.selectConversation('c2'))
    await waitFor(() => expect(result.current.items.map((m) => m.content)).toEqual(['other chat']))
    expect(listSolTurns).toHaveBeenLastCalledWith('p1', 'c2')
    expect(result.current.activeConversationId).toBe('c2')
  })

  it('startNewChat clears the active conversation and the transcript', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([turn('t1', 'user', 'old')])
    const { result } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    act(() => result.current.startNewChat())
    await waitFor(() => expect(result.current.items).toEqual([]))
    expect(result.current.activeConversationId).toBeNull()
    expect(useSolSessionStore.getState().conversationByProject).toEqual({})
  })
})

describe('cancelled turns never clobber newer sends (SOLUSDEV-233 review H1)', () => {
  it('a stale send’s cleanup leaves the newer live turn streaming and abortable', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    let rejectTurnA: (e: unknown) => void = () => undefined
    const signals: Array<AbortSignal | undefined> = []
    streamSolMessage
      .mockImplementationOnce(async ({ signal }) => {
        signals.push(signal)
        await new Promise((_, reject) => {
          rejectTurnA = reject
        })
      })
      .mockImplementationOnce(async ({ signal }) => {
        signals.push(signal)
        await new Promise(() => undefined) // turn B stays live
      })

    const { result, unmount } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      void result.current.send('turn A', 'guide')
    })
    // Switch chats (cancels A), then immediately send again on the new chat.
    act(() => result.current.selectConversation('c2'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      void result.current.send('turn B', 'guide')
    })
    expect(useSolSessionStore.getState().streaming).toBe(true)

    // Turn A's aborted fetch settles LATE — its cleanup must not turn off the
    // pulse or orphan turn B's abort handle.
    await act(async () => {
      rejectTurnA(new Error('aborted'))
      await Promise.resolve()
    })
    expect(useSolSessionStore.getState().streaming).toBe(true)

    // Teardown (sign-out path) must still be able to abort the live turn B —
    // unmount deliberately no longer does (sessions outlive the page).
    unmount()
    expect(signals[1]?.aborted).toBe(false)
    resetSolChatSessions()
    expect(signals[1]?.aborted).toBe(true)
    expect(useSolSessionStore.getState().streaming).toBe(false)
  })
})

describe('mid-stream credit exhaustion (security review L2)', () => {
  it('an insufficient_credits ERROR FRAME lights the top-up card too', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamWith([{ type: 'error', code: 'insufficient_credits', message: 'Not enough credits.' }])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.creditsExhausted).toBe(true)
    expect(result.current.items.at(-1)?.error).toBe('Not enough credits.')
  })
})

describe('several parked actions in one turn (SOLUSDEV-168)', () => {
  const parked = (id: string, tool: string): SolStreamEvent => ({
    type: 'tool_confirmation',
    pending: { confirmationId: id, tool, summary: `do ${tool}`, preview: [] }
  })

  it('keeps every card, because a dropped one is an action nobody can decide', async () => {
    // The turn no longer ends at the first parked call, so one message can park
    // several. The old single slot was overwritten, silently leaving only the
    // last — and a dropped card is a destructive action the user can neither
    // approve nor reject.
    createSolConversation.mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
    streamWith([
      parked('cf1', 'onshape.set_variable'),
      parked('cf2', 'onshape.add_feature'),
      { type: 'done', conversationId: 'c1', turnId: 't1' }
    ])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('make two changes', 'do')
    })

    const item = result.current.items.at(-1)
    expect(item?.confirmations.map((c) => c.confirmationId)).toEqual(['cf1', 'cf2'])
  })

  it('ignores a repeat of the same confirmation', async () => {
    createSolConversation.mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
    streamWith([
      parked('cf1', 'onshape.set_variable'),
      parked('cf1', 'onshape.set_variable'),
      { type: 'done', conversationId: 'c1', turnId: 't1' }
    ])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('again', 'do')
    })

    expect(result.current.items.at(-1)?.confirmations).toHaveLength(1)
  })

  it('deciding one leaves the others standing', async () => {
    createSolConversation.mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
    streamWith([
      parked('cf1', 'onshape.set_variable'),
      parked('cf2', 'onshape.add_feature'),
      { type: 'done', conversationId: 'c1', turnId: 't1' }
    ])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('two', 'do')
    })
    await act(async () => {
      await result.current.decide('cf1', 'approve')
    })

    expect(result.current.items.at(-1)?.confirmations.map((c) => c.confirmationId)).toEqual(['cf2'])
  })
})

describe('stable callbacks (SOLUSDEV-252 S2-A)', () => {
  it('keeps send/selectConversation/startNewChat/decide identical across re-renders', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([turn('t1', 'user', 'old')])
    const { result, rerender } = renderHook(({ pid }: { pid: string | null }) => useSolChat(pid), {
      initialProps: { pid: 'p1' }
    })
    const first = result.current
    await waitFor(() => expect(result.current.status).toBe('ready'))
    rerender({ pid: 'p1' })
    const again = result.current
    expect(again).not.toBe(first) // items changed → a new view object…
    expect(again.send).toBe(first.send) // …but every callback survived
    expect(again.selectConversation).toBe(first.selectConversation)
    expect(again.startNewChat).toBe(first.startNewChat)
    expect(again.decide).toBe(first.decide)

    rerender({ pid: 'p2' })
    expect(result.current.send).not.toBe(first.send)
    expect(result.current.decide).not.toBe(first.decide)
  })

  it('returns the same object when nothing it exposes changed', async () => {
    const { result, rerender } = renderHook(() => useSolChat('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const first = result.current
    rerender()
    expect(result.current).toBe(first)
  })
})
