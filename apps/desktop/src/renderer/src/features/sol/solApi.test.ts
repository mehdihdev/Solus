// SOLX-02: typed wrappers for the SOL conversation endpoints (API-implementation.md
// §11) + the streaming POST. SSE arrives on a POST, so the stream path is
// fetch + ReadableStream feeding the pure solStream parser — covered here with
// an injected fetch, no network.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from '../../lib/api/client'
import type { SolStreamEvent } from './solStream'
import { createSolConversation, listSolTurns, streamSolMessage } from './solApi'

function fakeClient(result: unknown): {
  client: ApiClient
  calls: Array<{ path: string; options?: unknown }>
} {
  const calls: Array<{ path: string; options?: unknown }> = []
  const client: ApiClient = {
    request: async <T>(path: string, options?: unknown): Promise<T> => {
      calls.push({ path, options })
      return result as T
    },
    requestPage: vi.fn()
  }
  return { client, calls }
}

function sseResponse(wire: string, init: { ok?: boolean; status?: number } = {}): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(wire))
      controller.close()
    }
  })
  return { ok: init.ok ?? true, status: init.status ?? 200, body } as unknown as Response
}

describe('conversation wrappers', () => {
  it('creates a conversation under the project scope', async () => {
    const { client, calls } = fakeClient({ id: 'c1' })
    const conversation = await createSolConversation('p1', client)
    expect(conversation.id).toBe('c1')
    expect(calls[0].path).toBe('/projects/p1/sol/conversations')
    expect(calls[0].options).toMatchObject({ method: 'POST' })
  })

  it('lists turns for an owned conversation', async () => {
    const { client, calls } = fakeClient([{ id: 't1' }])
    const turns = await listSolTurns('p1', 'c1', client)
    expect(turns).toEqual([{ id: 't1' }])
    expect(calls[0].path).toBe('/projects/p1/sol/conversations/c1/turns')
  })
})

describe('streamSolMessage', () => {
  const WIRE =
    'event: token\ndata: {"text":"Hi"}\n\n' +
    'event: message\ndata: {"role":"assistant","content":"Hi.","citations":["entity:imu"]}\n\n' +
    'event: done\ndata: {"conversation_id":"c1","turn_id":"t1"}\n\n'

  it('POSTs content + action_mode with the bearer token and streams parsed events', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    const events: SolStreamEvent[] = []
    await streamSolMessage({
      projectId: 'p1',
      conversationId: 'c1',
      content: 'why is the IMU noisy?',
      actionMode: 'do',
      onEvent: (e) => events.push(e),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => 'jwt-123',
      baseUrl: 'http://api.test/api/v1'
    })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://api.test/api/v1/projects/p1/sol/conversations/c1/messages')
    expect(init.method).toBe('POST')
    expect(init.headers).toMatchObject({
      Authorization: 'Bearer jwt-123',
      Accept: 'text/event-stream'
    })
    expect(JSON.parse(init.body as string)).toEqual({
      content: 'why is the IMU noisy?',
      action_mode: 'do'
    })
    expect(events.map((e) => e.type)).toEqual(['token', 'message', 'done'])
  })

  it('omits the Authorization header when unauthenticated', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    await streamSolMessage({
      projectId: 'p1',
      conversationId: 'c1',
      content: 'hello',
      actionMode: 'guide',
      onEvent: () => undefined,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => null,
      baseUrl: 'http://api.test'
    })
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.headers).not.toHaveProperty('Authorization')
  })

  it('rejects on a non-2xx status instead of parsing an error page', async () => {
    const fetchImpl = vi.fn(async () => sseResponse('', { ok: false, status: 429 }))
    await expect(
      streamSolMessage({
        projectId: 'p1',
        conversationId: 'c1',
        content: 'hello',
        actionMode: 'guide',
        onEvent: () => undefined,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        getToken: async () => null,
        baseUrl: 'http://api.test'
      })
    ).rejects.toMatchObject({ status: 429 })
  })
})

describe('path encoding (SOLX-02 Phase-4 security)', () => {
  it('percent-encodes a tampered conversation id instead of redirecting the request', async () => {
    // SEC-M3: ids come from persisted storage — a traversal-shaped value must
    // not aim a bearer-authenticated request at another endpoint.
    const { client, calls } = fakeClient({ data: [] })
    await listSolTurns('p1', '../../admin', client)
    expect(calls[0].path).not.toContain('../../admin')
    expect(calls[0].path).toContain('%2F')
  })
})
