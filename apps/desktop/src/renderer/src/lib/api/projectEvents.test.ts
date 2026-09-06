import { expect, it, vi } from 'vitest'
import { streamProjectEvents } from './projectEvents'

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
async function collect(fetchImpl: typeof fetch, signal?: AbortSignal): Promise<string[]> {
  const events: string[] = []
  for await (const event of streamProjectEvents({
    projectId: 'p1',
    baseUrl: 'https://api.test',
    getToken: () => 'test-session',
    fetchImpl,
    signal
  }))
    events.push(event)
  return events
}
it('authenticates once and accepts only complete events for the selected project', async () => {
  const fetchImpl = vi
    .fn()
    .mockResolvedValue(
      response([
        'event: ready\ndata: {"project_',
        'id":"p1"}\n\nevent: graph.changed\ndata: {"project_id":"foreign"}\n\n',
        ': keepalive\n\nevent: graph.changed\ndata: broken\n\n',
        'event: unknown\ndata: {"project_id":"p1"}\n\n',
        'event: graph.changed\ndata: {"project_id":"p1"}\n\n'
      ])
    )
  expect(await collect(fetchImpl)).toEqual(['ready', 'graph.changed'])
  expect(fetchImpl).toHaveBeenCalledWith(
    'https://api.test/projects/p1/events',
    expect.objectContaining({
      method: 'GET',
      headers: { Accept: 'text/event-stream', Authorization: 'Bearer test-session' }
    })
  )
})
it('retains authorization status for reconnect policy', async () => {
  await expect(
    collect(vi.fn().mockResolvedValue(new Response(null, { status: 403 })))
  ).rejects.toMatchObject({ status: 403 })
})
it('bounds incomplete frames and cancels their reader', async () => {
  const cancel = vi.fn()
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('x'.repeat(70_000)))
    },
    cancel
  })
  await expect(collect(vi.fn().mockResolvedValue(new Response(body)))).rejects.toThrow('too large')
  expect(cancel).toHaveBeenCalledOnce()
})
it('does not send an already cancelled subscription', async () => {
  const controller = new AbortController()
  controller.abort()
  const fetchImpl = vi.fn()
  await expect(collect(fetchImpl, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchImpl).not.toHaveBeenCalled()
})
