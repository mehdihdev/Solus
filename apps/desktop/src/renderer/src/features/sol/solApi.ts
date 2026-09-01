// SOLX-02: typed wrappers over the SOL chat endpoints (SOLUSDEV-135 backend,
// API-implementation.md §11) — project-scoped, owner-private conversations.
// JSON endpoints ride the shared typed client; the streaming turn is the one
// endpoint the envelope client cannot carry (SSE arrives on a POST), so it
// uses fetch + ReadableStream here — in this module, never raw fetch in
// components — and feeds the pure solStream parser.
import { api, joinUrl, type ApiClient } from '../../lib/api/client'
import { resolveApiBaseUrl } from '../../lib/cspConnect'
import { ApiError } from '../../lib/api/envelope.types'
import { createSolStreamParser, type SolStreamEvent } from './solStream'

/** How SOL may act on one message: explain and point, or operate tools (SOLX-01). */
export type SolActionMode = 'guide' | 'do'

export interface SolConversation {
  id: string
  project_id: string
  title: string | null
  created_by: string
  created_at: string
  updated_at: string
}

/** One persisted turn as served by GET …/turns (newest first). */
export interface SolTurn {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  attrs: Record<string, unknown>
  created_at: string
}

export function createSolConversation(
  projectId: string,
  title?: string,
  client: ApiClient = api
): Promise<SolConversation> {
  return client.request<SolConversation>(
    `/projects/${encodeURIComponent(projectId)}/sol/conversations`,
    {
      method: 'POST',
      body: title === undefined ? {} : { title }
    }
  )
}

/** The caller's conversations for the project, newest first (SOLUSDEV-233). */
export function listSolConversations(
  projectId: string,
  client: ApiClient = api
): Promise<SolConversation[]> {
  return client.request<SolConversation[]>(
    `/projects/${encodeURIComponent(projectId)}/sol/conversations`
  )
}

/** Rename an owned conversation (SOLUSDEV-233 sidebar context menu). */
export function renameSolConversation(
  projectId: string,
  conversationId: string,
  title: string,
  client: ApiClient = api
): Promise<SolConversation> {
  return client.request<SolConversation>(
    `/projects/${encodeURIComponent(projectId)}/sol/conversations/${encodeURIComponent(conversationId)}`,
    { method: 'PATCH', body: { title } }
  )
}

/** Soft-delete an owned conversation (SOLUSDEV-233). */
export function deleteSolConversation(
  projectId: string,
  conversationId: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(
    `/projects/${encodeURIComponent(projectId)}/sol/conversations/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' }
  )
}

/** Latest page of turns, newest first (the UI reverses for display). */
export function listSolTurns(
  projectId: string,
  conversationId: string,
  client: ApiClient = api
): Promise<SolTurn[]> {
  return client.request<SolTurn[]>(
    `/projects/${encodeURIComponent(projectId)}/sol/conversations/${encodeURIComponent(conversationId)}/turns`
  )
}

// Same resolution as lib/api/client.ts, through the shared helper so the two can
// never disagree. This used `??`, which only catches null/undefined — a blank
// `VITE_API_BASE_URL=` therefore survived as '', and `joinUrl('', …)` yields a
// RELATIVE url resolved against the renderer's own origin, so every SOL turn and
// stream missed the API. Hermeticity no longer rides on blank: vitest pins an
// unroutable `.invalid` host instead (see vitest.config.ts).
const DEFAULT_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL)

async function defaultToken(): Promise<string | null> {
  // Lazy import to avoid a module-load cycle with the store (client.ts idiom).
  const { useAuthStore } = await import('../../store/authStore')
  return useAuthStore.getState().accessToken
}

export interface StreamSolMessageInput {
  projectId: string
  conversationId: string
  content: string
  actionMode: SolActionMode
  /** Receives each validated stream event in arrival order. */
  onEvent: (event: SolStreamEvent) => void
  signal?: AbortSignal
  fetchImpl?: typeof fetch
  getToken?: () => Promise<string | null>
  baseUrl?: string
}

/**
 * POST one user message and stream SOL's reply. Resolves when the stream ends;
 * rejects on a non-2xx status or transport failure. Malformed frames are
 * dropped by the parser, never delivered.
 */
export async function streamSolMessage(input: StreamSolMessageInput): Promise<void> {
  const fetchImpl = input.fetchImpl ?? globalThis.fetch
  const token = await (input.getToken ?? defaultToken)()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream'
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const path = `/projects/${encodeURIComponent(input.projectId)}/sol/conversations/${encodeURIComponent(input.conversationId)}/messages`
  const res = await fetchImpl(joinUrl(input.baseUrl ?? DEFAULT_BASE_URL, path), {
    method: 'POST',
    headers,
    body: JSON.stringify({ content: input.content, action_mode: input.actionMode }),
    signal: input.signal
  })
  if (!res.ok || res.body === null) {
    throw new ApiError(res.status, 'sol_stream_failed', `SOL stream failed (${res.status})`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSolStreamParser()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      input.onEvent(event)
    }
  }
}
