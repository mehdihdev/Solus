import { describe, expect, it, vi } from 'vitest'
import { LiveStreamFrameTooLargeError, LiveStreamHttpError, streamSse } from './liveStream'

function response(chunks: string[]): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
        controller.close()
      }
    })
  )
}
const decode = (event: { type: string; data: Record<string, unknown> }): string | null =>
  event.type === 'ping' ? String(event.data.n) : null

async function collect(
  fetchImpl: typeof fetch,
  extra: { signal?: AbortSignal; maxFrameBytes?: number } = {}
): Promise<string[]> {
  const out: string[] = []
  for await (const item of streamSse({
    path: '/things/events',
    baseUrl: 'https://api.test',
    getToken: () => 'tok',
    fetchImpl,
    decode,
    ...extra
  }))
    out.push(item)
  return out
}

describe('streamSse', () => {
  it('sends a Bearer GET and yields decoded frames across chunk boundaries', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        response(['event: ping\ndata: {"n"', ':1}\n\nevent: ping\ndata: {"n":2}\n\n'])
      )
    expect(await collect(fetchImpl)).toEqual(['1', '2'])
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://api.test/things/events',
      expect.objectContaining({
        method: 'GET',
        headers: { Accept: 'text/event-stream', Authorization: 'Bearer tok' }
      })
    )
  })

  it('omits Authorization when there is no token', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response([]))
    for await (const _ of streamSse({
      path: '/x',
      baseUrl: 'https://api.test',
      getToken: () => null,
      fetchImpl,
      decode
    }))
      void _
    expect(fetchImpl.mock.calls[0]?.[1].headers).toEqual({ Accept: 'text/event-stream' })
  })

  it('ignores comments, malformed JSON and frames the decoder rejects', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        response([
          ': keepalive\n\nevent: ping\ndata: broken\n\nevent: other\ndata: {"n":9}\n\n',
          'event: ping\ndata: {"n":3}\n\n'
        ])
      )
    expect(await collect(fetchImpl)).toEqual(['3'])
  })

  it('throws LiveStreamHttpError carrying the status on a non-2xx response', async () => {
    const error = await collect(
      vi.fn().mockResolvedValue(new Response(null, { status: 429 }))
    ).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(LiveStreamHttpError)
    expect(error).toMatchObject({ status: 429 })
  })

  it('bounds an incomplete frame, cancels the reader and throws', async () => {
    const cancel = vi.fn()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('x'.repeat(100)))
      },
      cancel
    })
    const run = collect(vi.fn().mockResolvedValue(new Response(body)), { maxFrameBytes: 64 })
    await expect(run).rejects.toBeInstanceOf(LiveStreamFrameTooLargeError)
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('uses a 64 KB default frame cap', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('x'.repeat(70_000)))
      }
    })
    await expect(collect(vi.fn().mockResolvedValue(new Response(body)))).rejects.toThrow(
      'too large'
    )
  })

  it('does not send an already-cancelled subscription', async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchImpl = vi.fn()
    await expect(collect(fetchImpl, { signal: controller.signal })).rejects.toMatchObject({
      name: 'AbortError'
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })
})
