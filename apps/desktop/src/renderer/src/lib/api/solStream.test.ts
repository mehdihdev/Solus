// SOL SSE stream parsing. The interesting behaviour is chunk boundaries —
// network chunks do not align with frames — so the parser is pure and tested
// without a network.
import { describe, expect, it, vi } from 'vitest'
import {
  parseSseBuffer,
  parseSseFrame,
  streamSolTurn,
  toPendingConfirmation,
  type SolEvent
} from './solStream'

const FRAME = 'event: token\ndata: {"delta":"hi"}\n\n'

describe('parseSseFrame', () => {
  it('reads the event type and JSON payload', () => {
    expect(parseSseFrame('event: token\ndata: {"delta":"hi"}')).toEqual({
      type: 'token',
      data: { delta: 'hi' }
    })
  })

  it('skips a frame with no event type rather than throwing', () => {
    expect(parseSseFrame('data: {"a":1}')).toBeNull()
  })

  it('skips malformed JSON rather than killing the turn', () => {
    expect(parseSseFrame('event: token\ndata: {not json')).toBeNull()
  })

  it('treats a frame with no data as an empty payload', () => {
    expect(parseSseFrame('event: done')).toEqual({ type: 'done', data: {} })
  })
})

describe('parseSseBuffer', () => {
  it('returns complete frames and carries the remainder', () => {
    const { events, rest } = parseSseBuffer(FRAME + 'event: done\ndata: {"turn"')

    expect(events).toEqual([{ type: 'token', data: { delta: 'hi' } }])
    expect(rest).toBe('event: done\ndata: {"turn"')
  })

  it('reassembles a frame split across two chunks', () => {
    const first = parseSseBuffer('event: token\ndata: {"del')
    const second = parseSseBuffer(first.rest + 'ta":"hi"}\n\n')

    expect(first.events).toEqual([])
    expect(second.events).toEqual([{ type: 'token', data: { delta: 'hi' } }])
  })

  it('handles several frames arriving in one chunk', () => {
    const { events } = parseSseBuffer(FRAME + FRAME + FRAME)

    expect(events).toHaveLength(3)
  })
})

describe('toPendingConfirmation', () => {
  const event = (data: Record<string, unknown>): SolEvent => ({ type: 'tool_confirmation', data })

  it('reads the action and its diff', () => {
    const pending = toPendingConfirmation(
      event({
        confirmation_id: 'c1',
        tool: 'onshape.set_variable',
        summary: 'Change width',
        preview: [{ label: 'width', before: '100 mm', after: '120 mm' }]
      })
    )

    expect(pending?.confirmationId).toBe('c1')
    expect(pending?.preview).toEqual([{ label: 'width', before: '100 mm', after: '120 mm' }])
  })

  it('drops preview rows without a label — the payload is untrusted', () => {
    const pending = toPendingConfirmation(
      event({ confirmation_id: 'c1', tool: 't', preview: [{ before: 'x' }, 'nope', null] })
    )

    expect(pending?.preview).toEqual([])
  })

  it('falls back to the tool name when no summary is sent', () => {
    expect(toPendingConfirmation(event({ confirmation_id: 'c1', tool: 't' }))?.summary).toBe('t')
  })

  it('returns null when the payload cannot identify an action', () => {
    expect(toPendingConfirmation(event({ tool: 't' }))).toBeNull()
  })

  it('tolerates a missing preview — not every tool can describe its change', () => {
    expect(toPendingConfirmation(event({ confirmation_id: 'c1', tool: 't' }))?.preview).toEqual([])
  })
})

describe('streamSolTurn', () => {
  function bodyOf(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    return new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      }
    })
  }

  async function collect(fetchImpl: typeof fetch): Promise<SolEvent[]> {
    const events: SolEvent[] = []
    for await (const event of streamSolTurn({
      projectId: 'p1',
      conversationId: 'c1',
      content: 'hello',
      baseUrl: 'http://api.test',
      getToken: () => 'tok',
      fetchImpl
    })) {
      events.push(event)
    }
    return events
  }

  it('yields events as they arrive, across chunk boundaries', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          bodyOf(['event: token\ndata: {"del', 'ta":"hi"}\n\nevent: done\ndata: {}\n\n']),
          {
            status: 200
          }
        )
    ) as unknown as typeof fetch

    expect(await collect(fetchImpl)).toEqual([
      { type: 'token', data: { delta: 'hi' } },
      { type: 'done', data: {} }
    ])
  })

  it('sends the bearer token and asks for an event stream', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(bodyOf(['event: done\ndata: {}\n\n']), { status: 200 })
    ) as unknown as typeof fetch

    await collect(fetchImpl)

    const [, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers.Accept).toBe('text/event-stream')
  })

  it('surfaces a failed request as one error event rather than throwing', async () => {
    const fetchImpl = vi.fn(
      async () => new Response('nope', { status: 500 })
    ) as unknown as typeof fetch

    const events = await collect(fetchImpl)

    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('error')
  })
})
