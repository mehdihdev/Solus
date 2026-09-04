// SOLUSDEV-235 / EXT-12 — `sol.ask` (§6.6). The host makes the ordinary SOL
// turn with the USER's session plus `X-Solus-Extension` / `-Version`; the
// server verifies the install + grant, meters the user, attributes the
// extension, and wraps the prompt as data. The frame gets TEXT back and the
// host never renders it.
//
// The streaming turn cannot ride the JSON envelope client (SSE on a POST) and
// the existing `streamSolMessage` takes no extra headers, so the attributed
// POST is made here — fetch in this module only, never in components.
import { apiBaseUrl, apiToken, joinUrl } from '../../../../lib/api/client'
import { ApiError } from '../../../../lib/api/envelope.types'
import { withExtensionAttribution } from '../../../../lib/api/resources.extensions'
import { createSolConversation } from '../../../sol/solApi'
import { createSolStreamParser } from '../../../sol/solStream'
import type { BridgeSolDeps, SolAskInput } from '../bridgeDeps'
import { BridgeFault } from '../bridgeErrors'
import type { HandlerTable } from './context'

export const solHandlers: HandlerTable<'sol.ask'> = {
  'sol.ask': async (p, ctx) => ({
    answer: await ctx.deps.sol.ask({ policy: ctx.policy, prompt: p.prompt, entityIds: p.entityIds })
  })
}

export interface AttributedSolTransport {
  baseUrl?: string
  getToken?: () => Promise<string | null> | string | null
  fetchImpl?: typeof fetch
  /** Injectable for tests; defaults to the typed client's conversation create. */
  createConversation?: (projectId: string, title: string) => Promise<{ id: string }>
}

async function readAnswer(body: ReadableStream<Uint8Array>): Promise<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const parser = createSolStreamParser()
  let message: string | null = null
  const tokens: string[] = []
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      if (event.type === 'token') tokens.push(event.text)
      else if (event.type === 'message' && event.role === 'assistant') message = event.content
      else if (event.type === 'error') throw new BridgeFault('unavailable')
    }
  }
  return message ?? tokens.join('')
}

async function envelopeError(res: Response): Promise<ApiError> {
  let code = 'sol_turn_failed'
  let message = `SOL returned ${res.status}`
  try {
    const parsed = (await res.json()) as { error?: { code?: string; message?: string } }
    code = parsed.error?.code ?? code
    message = parsed.error?.message ?? message
  } catch {
    // Non-JSON body: keep the generic code; toBridgeError maps by status.
  }
  return new ApiError(res.status, code, message)
}

/**
 * The default `BridgeSolDeps`: one conversation per (project, extension) for
 * the life of this host, created lazily and titled after the extension so it
 * reads honestly in the user's chat sidebar; each ask is one guide-mode turn.
 */
export function createAttributedSolAsk(transport: AttributedSolTransport = {}): BridgeSolDeps {
  const conversations = new Map<string, Promise<string>>()
  const createConversation =
    transport.createConversation ??
    ((projectId: string, title: string) => createSolConversation(projectId, title))

  function conversationFor(projectId: string, extensionId: string): Promise<string> {
    const key = `${projectId}:${extensionId}`
    const existing = conversations.get(key)
    if (existing) return existing
    const created = createConversation(projectId, `Extension: ${extensionId}`).then((c) => c.id)
    conversations.set(key, created)
    created.catch(() => conversations.delete(key))
    return created
  }

  async function ask({ policy, prompt }: SolAskInput): Promise<string> {
    const conversationId = await conversationFor(policy.projectId, policy.extensionId)
    const token = await (transport.getToken ?? apiToken)()
    const fetchImpl = transport.fetchImpl ?? globalThis.fetch
    const path = `/projects/${encodeURIComponent(policy.projectId)}/sol/conversations/${encodeURIComponent(conversationId)}/messages`
    const res = await fetchImpl(joinUrl(transport.baseUrl ?? apiBaseUrl, path), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...withExtensionAttribution(policy.extensionId, policy.version)
      },
      body: JSON.stringify({ content: prompt, action_mode: 'guide' })
    })
    if (!res.ok) throw await envelopeError(res)
    if (res.body === null) throw new BridgeFault('unavailable')
    return readAnswer(res.body)
  }

  return { ask }
}
