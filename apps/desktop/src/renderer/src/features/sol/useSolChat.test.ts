// SOLX-02: chat state — per-project history, conversation creation on first
// send, streamed tokens folding into the pending assistant item, tool trace,
// structured citations, and the orbStore streaming flag around a turn.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import type { SolStreamEvent } from './solStream'
import { useOrbStore } from './orbStore'
import { useSolChat } from './useSolChat'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
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
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
})

describe('history', () => {
  it('loads the stored conversation, oldest first', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
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
    useOrbStore.getState().setConversation('p1', 'c1')
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
    expect(createSolConversation).toHaveBeenCalledWith('p1')
    expect(useOrbStore.getState().conversationByProject).toEqual({ p1: 'c9' })
    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: 'c9', content: 'hello', actionMode: 'guide' })
    )
  })

  it('passes the chosen action mode through to the stream', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamWith([])
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('flash it', 'do')
    })
    expect(streamSolMessage).toHaveBeenCalledWith(expect.objectContaining({ actionMode: 'do' }))
  })

  it('folds tokens into the pending assistant item, finalizes on message, pulses orbStore', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    const seenStreaming: boolean[] = []
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      seenStreaming.push(useOrbStore.getState().streaming)
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
    expect(useOrbStore.getState().streaming).toBe(false) // and off after
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
    useOrbStore.getState().setConversation('p1', 'c1')
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
    useOrbStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([])
    streamSolMessage.mockRejectedValue(new Error('ECONNREFUSED'))
    const { result } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      await result.current.send('hi', 'guide')
    })
    expect(result.current.items[1].error).toBe('SOL is unreachable right now.')
    expect(result.current.items[1].error).not.toContain('ECONNREFUSED')
    expect(useOrbStore.getState().streaming).toBe(false)
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

describe('stream lifecycle (SOLX-02 Phase-4 security)', () => {
  it('aborts the in-flight stream on unmount and clears the streaming flag', async () => {
    // SEC-H3: an unmounted panel must not leave a read running.
    let seen: AbortSignal | undefined
    streamSolMessage.mockImplementation(async ({ signal }) => {
      seen = signal
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    listSolTurns.mockResolvedValue([])
    useOrbStore.getState().setConversation('p1', 'c1')

    const { result, unmount } = renderHook(() => useSolChat('p1'))
    await act(async () => {
      void result.current.send('hello', 'guide')
    })
    unmount()

    expect(seen).toBeDefined()
    expect(seen?.aborted).toBe(true)
    expect(useOrbStore.getState().streaming).toBe(false)
  })

  it('bounds per-turn content so a runaway stream cannot grow without limit', async () => {
    listSolTurns.mockResolvedValue([])
    useOrbStore.getState().setConversation('p1', 'c1')
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
