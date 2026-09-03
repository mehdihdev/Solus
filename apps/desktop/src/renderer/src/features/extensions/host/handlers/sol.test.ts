// SOLUSDEV-235 / EXT-12 — the attributed SOL turn (§6.6): user session +
// X-Solus-Extension headers on the request, text-only answer back, and the
// token appears NOWHERE but the Authorization header.
import { describe, it, expect, vi } from 'vitest'
import { toBridgeError } from '../bridgeErrors'
import type { BridgePolicy } from '../policySnapshot'
import { createAttributedSolAsk } from './sol'

const policy: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: ['sol.ask'],
  grantedNetwork: [],
  enabled: true,
  blocked: false,
  mode: 'widget'
}

const TOKEN = 'tok-secret-9f2c'

function sse(frames: [string, unknown][]): string {
  return frames.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join('')
}

function harness(
  status: number,
  body: string
): {
  ask: ReturnType<typeof createAttributedSolAsk>
  calls: { url: string; init: RequestInit }[]
  createConversation: ReturnType<typeof vi.fn>
} {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} })
    return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } })
  }) as unknown as typeof fetch
  const createConversation = vi.fn(async () => ({ id: 'conv-1' }))
  const ask = createAttributedSolAsk({
    baseUrl: 'https://api.test/api/v1',
    getToken: () => TOKEN,
    fetchImpl,
    createConversation
  })
  return { ask, calls, createConversation }
}

describe('createAttributedSolAsk', () => {
  it('POSTs the turn with the user token and the attribution headers, returns the answer text', async () => {
    const { ask, calls, createConversation } = harness(
      200,
      sse([
        ['token', { text: 'Hel' }],
        ['token', { text: 'lo' }],
        ['message', { role: 'assistant', content: 'Hello.', citations: [] }],
        ['done', { conversation_id: 'conv-1', turn_id: 't1' }]
      ])
    )
    const answer = await ask.ask({ policy, prompt: 'What drives the motor?', entityIds: ['e1'] })
    expect(answer).toBe('Hello.')
    expect(createConversation).toHaveBeenCalledWith('p1', 'Extension: bom')
    expect(calls[0].url).toBe(
      'https://api.test/api/v1/projects/p1/sol/conversations/conv-1/messages'
    )
    const headers = calls[0].init.headers as Record<string, string>
    expect(headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(headers['X-Solus-Extension']).toBe('bom')
    expect(headers['X-Solus-Extension-Version']).toBe('1.2.0')
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      content: 'What drives the motor?',
      action_mode: 'guide'
    })
  })

  it('falls back to the concatenated tokens when no message frame arrives', async () => {
    const { ask } = harness(
      200,
      sse([
        ['token', { text: 'a' }],
        ['token', { text: 'b' }]
      ])
    )
    expect(await ask.ask({ policy, prompt: 'q', entityIds: [] })).toBe('ab')
  })

  it('reuses one conversation per (project, extension)', async () => {
    const { ask, createConversation } = harness(200, sse([['token', { text: 'x' }]]))
    await ask.ask({ policy, prompt: 'a', entityIds: [] })
    await ask.ask({ policy, prompt: 'b', entityIds: [] })
    expect(createConversation).toHaveBeenCalledTimes(1)
  })

  it('a 403 scope_denied surfaces as the bridge scope_denied without the server text', async () => {
    const { ask } = harness(
      403,
      JSON.stringify({ error: { code: 'scope_denied', message: 'install row missing for p1' } })
    )
    const error = await ask.ask({ policy, prompt: 'q', entityIds: [] }).catch((e: unknown) => e)
    const mapped = toBridgeError(error)
    expect(mapped.code).toBe('scope_denied')
    expect(mapped.message).not.toContain('install row')
  })

  it('a stream error frame is unavailable', async () => {
    const { ask } = harness(200, sse([['error', { code: 'model_failed', message: 'nope' }]]))
    const error = await ask.ask({ policy, prompt: 'q', entityIds: [] }).catch((e: unknown) => e)
    expect(toBridgeError(error).code).toBe('unavailable')
  })

  it('the token never appears in what the frame receives', async () => {
    const { ask } = harness(
      200,
      sse([['message', { role: 'assistant', content: 'ok', citations: [] }]])
    )
    const answer = await ask.ask({ policy, prompt: 'q', entityIds: [] })
    expect(answer).not.toContain(TOKEN)
  })
})
