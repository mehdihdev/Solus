// Generic fetch-based SSE transport for the live channels (ADR-037). `fetch` is
// used here and in solStream only: the typed client wraps JSON request/response,
// which a streaming body is not. Callers supply a `decode` that turns a parsed
// frame into a typed value or null (dropped) — decoding never throws.
import { apiBaseUrl, apiToken, joinUrl } from './client'
import { parseSseBuffer, type SolEvent } from './solStream'

/** Largest unterminated frame we will buffer before giving up on the stream. */
export const DEFAULT_MAX_FRAME_BYTES = 65_536

/** The stream endpoint answered non-2xx; `status` drives the reconnect policy. */
export class LiveStreamHttpError extends Error {
  readonly status: number
  constructor(status: number, message = 'Live updates disconnected.') {
    super(message)
    this.name = 'LiveStreamHttpError'
    this.status = status
  }
}

export class LiveStreamFrameTooLargeError extends Error {
  constructor() {
    super('Live stream frame is too large.')
    this.name = 'LiveStreamFrameTooLargeError'
  }
}

export interface StreamSseOptions<T> {
  /** Path under the API base, e.g. `/users/me/events`. */
  path: string
  signal?: AbortSignal
  decode: (event: SolEvent) => T | null
  maxFrameBytes?: number
  baseUrl?: string
  getToken?: () => string | null | Promise<string | null>
  fetchImpl?: typeof fetch
}

async function open<T>(options: StreamSseOptions<T>): Promise<ReadableStream<Uint8Array>> {
  const token = await (options.getToken ?? apiToken)()
  options.signal?.throwIfAborted()
  const response = await (options.fetchImpl ?? fetch)(
    joinUrl(options.baseUrl ?? apiBaseUrl, options.path),
    {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      signal: options.signal
    }
  )
  if (!response.ok || !response.body) throw new LiveStreamHttpError(response.status)
  return response.body
}

export async function* streamSse<T>(options: StreamSseOptions<T>): AsyncGenerator<T> {
  const cap = options.maxFrameBytes ?? DEFAULT_MAX_FRAME_BYTES
  const reader = (await open(options)).getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseBuffer(buffer)
      buffer = parsed.rest
      if (buffer.length > cap) throw new LiveStreamFrameTooLargeError()
      for (const event of parsed.events) {
        const decoded = options.decode(event)
        if (decoded !== null) yield decoded
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
