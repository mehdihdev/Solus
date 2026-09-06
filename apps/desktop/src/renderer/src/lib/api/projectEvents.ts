// Authenticated, project-scoped invalidation hints from the existing Solus SSE
// endpoint. This typed transport never calls a provider or requests a sync.
import { joinUrl } from './client'
import { ApiError } from './envelope.types'
import { parseSseBuffer } from './solStream'

interface ProjectEventOptions {
  projectId: string
  baseUrl: string
  getToken: () => string | null | Promise<string | null>
  signal?: AbortSignal
  fetchImpl?: typeof fetch
}
export type ProjectEvent = 'ready' | 'graph.changed'
async function openProjectStream(
  options: ProjectEventOptions
): Promise<ReadableStream<Uint8Array>> {
  const token = await options.getToken()
  options.signal?.throwIfAborted()
  const response = await (options.fetchImpl ?? fetch)(
    joinUrl(options.baseUrl, `/projects/${options.projectId}/events`),
    {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      signal: options.signal
    }
  )
  if (!response.ok || !response.body)
    throw new ApiError(response.status, 'project_stream_failed', 'Live updates disconnected.')
  return response.body
}

export async function* streamProjectEvents(
  options: ProjectEventOptions
): AsyncGenerator<ProjectEvent> {
  const body = await openProjectStream(options)
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseBuffer(buffer)
      buffer = parsed.rest
      if (buffer.length > 65_536) throw new Error('Project event frame is too large.')
      for (const event of parsed.events) {
        if (event.data.project_id !== options.projectId) continue
        if (event.type === 'ready' || event.type === 'graph.changed') yield event.type
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
