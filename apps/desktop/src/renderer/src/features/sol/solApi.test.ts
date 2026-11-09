// SOLX-02: typed wrappers for the SOL conversation endpoints (API-implementation.md
// §11) + the streaming POST. SSE arrives on a POST, so the stream path is
// fetch + ReadableStream feeding the pure solStream parser — covered here with
// an injected fetch, no network.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from '../../lib/api/client'
import type { SolStreamEvent } from './solStream'
import {
  createSolConversation,
  deleteSolConversation,
  fetchArtifactBlob,
  listSolConversations,
  listSolTurns,
  renameSolConversation,
  streamSolMessage
} from './solApi'

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
    const conversation = await createSolConversation('p1', undefined, client)
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
  messageRequestRoutingTests(WIRE)
  messageRequestScreenshotTests(WIRE)
  messageRequestContextTests(WIRE)
  messageRequestAnchorTests(WIRE)
  messageRequestAuthorizationTests(WIRE)
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

describe('conversation list/delete (SOLUSDEV-233)', () => {
  it('lists the caller’s conversations for the project', async () => {
    const { client, calls } = fakeClient([{ id: 'c1', title: 'Project recap' }])
    const list = await listSolConversations('p1', client)
    expect(list[0].id).toBe('c1')
    expect(calls[0].path).toBe('/projects/p1/sol/conversations')
  })

  it('deletes an owned conversation', async () => {
    const { client, calls } = fakeClient(undefined)
    await deleteSolConversation('p1', 'c1', client)
    expect(calls[0].path).toBe('/projects/p1/sol/conversations/c1')
    expect(calls[0].options).toMatchObject({ method: 'DELETE' })
  })

  it('creates a conversation with a title seeded from the first message', async () => {
    const { client, calls } = fakeClient({ id: 'c9' })
    await createSolConversation('p1', 'Why is joint 2 stalling?', client)
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { title: 'Why is joint 2 stalling?' }
    })
  })
})

describe('conversation rename (SOLUSDEV-233 context menu)', () => {
  it('PATCHes the new title to the owned conversation', async () => {
    const { client, calls } = fakeClient({ id: 'c1', title: 'Diagnose run 41' })
    await renameSolConversation('p1', 'c1', 'Diagnose run 41', client)
    expect(calls[0].path).toBe('/projects/p1/sol/conversations/c1')
    expect(calls[0].options).toMatchObject({
      method: 'PATCH',
      body: { title: 'Diagnose run 41' }
    })
  })
})

// SOLUSDEV-252 S5: artifact bytes need the bearer, so they cannot ride an
// `<img src>` — fetched here, handed back as a Blob for an object URL.
describe('fetchArtifactBlob', () => {
  it('GETs the content route with the bearer and returns the bytes as a Blob', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response('<svg xmlns="http://www.w3.org/2000/svg"/>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml' }
        })
    )
    const blob = await fetchArtifactBlob('p1', 'a1', {
      fetchImpl,
      getToken: async () => 'tok',
      baseUrl: 'http://api.test/api/v1'
    })
    expect(blob.type).toBe('image/svg+xml')
    expect(blob.size).toBeGreaterThan(0)
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://api.test/api/v1/projects/p1/artifacts/a1/content')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
  })

  it('throws the envelope error on a refusal, never a blob of the error body', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: 'not_found', message: 'gone' } }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' }
        })
    )
    await expect(
      fetchArtifactBlob('p1', 'a1', { fetchImpl, getToken: async () => 'tok', baseUrl: 'http://x' })
    ).rejects.toMatchObject({ status: 404, message: 'gone' })
  })
})

function messageRequestRoutingTests(WIRE: string): void {
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
      action_mode: 'do',
      // Always present, so the server sees one body shape (SOLUSDEV-168).
      mentions: []
    })
    expect(events.map((e) => e.type)).toEqual(['token', 'message', 'done'])
  })

  it('sends think_harder only when the composer toggle is on', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    const base = {
      projectId: 'p1',
      conversationId: 'c1',
      content: 'what is I2C',
      actionMode: 'guide' as const,
      onEvent: () => {},
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => null,
      baseUrl: 'http://api.test/api/v1'
    }
    await streamSolMessage({ ...base, thinkHarder: true })
    await streamSolMessage({ ...base, thinkHarder: false })
    await streamSolMessage(base)
    const bodies = fetchImpl.mock.calls.map(
      (call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string) as object
    )
    expect(bodies[0]).toMatchObject({ think_harder: true })
    expect(bodies[1]).not.toHaveProperty('think_harder')
    expect(bodies[2]).not.toHaveProperty('think_harder')
  })
}

function messageRequestScreenshotTests(WIRE: string): void {
  it('posts the screenshot as `screenshot` (crop + context) only when one is attached', async () => {
    // SOLUSDEV-252 S3 (docs/architecture/sol-window.md §8): at most one per turn.
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    const base = {
      projectId: 'p1',
      conversationId: 'c1',
      content: 'What do you think this is?',
      actionMode: 'guide' as const,
      onEvent: () => {},
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => null,
      baseUrl: 'http://api.test/api/v1'
    }
    const screenshot = {
      media_type: 'image/png' as const,
      data: 'iVBORw0KGgo=',
      width: 320,
      height: 200,
      source: { app: 'Onshape', title: 'Bracket v3' },
      context: 'iVBORw0KGgoCONTEXT='
    }
    await streamSolMessage({ ...base, screenshot })
    await streamSolMessage(base)
    const bodies = fetchImpl.mock.calls.map(
      (call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string) as object
    )
    expect(bodies[0]).toMatchObject({ screenshot })
    expect(bodies[1]).not.toHaveProperty('screenshot')
  })
}

function messageRequestContextTests(WIRE: string): void {
  it('sends the engineering preferences beside the text, and omits the key when null', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    const preferences = {
      schema_version: 1,
      freeText: '',
      codeStyle: '',
      mechanical: '',
      electrical: 'Prefer 0.1 mm clearance minimum on all boards.',
      documentation: '',
      unitsStandards: ''
    }
    const base = {
      projectId: 'p1',
      conversationId: 'c1',
      content: 'what clearance?',
      actionMode: 'guide' as const,
      onEvent: () => undefined,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => 'jwt',
      baseUrl: 'http://api.test/api/v1'
    }
    await streamSolMessage({ ...base, preferences })
    await streamSolMessage({ ...base, preferences: null })
    const bodies = fetchImpl.mock.calls.map(
      (call) =>
        JSON.parse((call as unknown as [string, RequestInit])[1].body as string) as Record<
          string,
          unknown
        >
    )
    expect(bodies[0].preferences).toEqual(preferences)
    expect('preferences' in bodies[1]).toBe(false)
  })

  it('sends @-mentioned entity ids beside the text, never encoded into it', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    await streamSolMessage({
      projectId: 'p1',
      conversationId: 'c1',
      content: 'will @Camera Bracket clear the belt?',
      actionMode: 'do',
      mentions: ['e-1', 'e-2'],
      onEvent: () => undefined,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => null,
      baseUrl: 'http://api.test/api/v1'
    })
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(init.body as string).mentions).toEqual(['e-1', 'e-2'])
  })
}

function messageRequestAnchorTests(WIRE: string): void {
  it('body carries focus and pins only when set', async () => {
    // Canonical UUIDs: the server parses every anchor id as one.
    const id = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
    // SOLUSDEV-321 P0-T3: where the person is looking, the chat's pinned nodes, a finding
    // and a bench robot are anchors of their own — never folded into `mentions`. Each key is
    // sent only when it has something to say, so the default body stays the minimal one.
    const fetchImpl = vi.fn(async () => sseResponse(WIRE))
    const base = {
      projectId: 'p1',
      conversationId: 'c1',
      content: 'why is this hot?',
      actionMode: 'guide' as const,
      onEvent: () => undefined,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: async () => null,
      baseUrl: 'http://api.test/api/v1'
    }
    await streamSolMessage({
      ...base,
      focus: { entityId: id(1), path: [id(2)] },
      pins: [id(3), id(4)],
      findingId: id(5),
      robotId: id(6)
    })
    await streamSolMessage({ ...base, focus: { entityId: id(7), path: [] } })
    await streamSolMessage({ ...base, pins: [] })
    await streamSolMessage(base)
    const bodies = fetchImpl.mock.calls.map(
      (call) =>
        JSON.parse((call as unknown as [string, RequestInit])[1].body as string) as Record<
          string,
          unknown
        >
    )
    expect(bodies[0]).toMatchObject({
      focus: { entity_id: id(1), path: [id(2)] },
      pins: [id(3), id(4)],
      finding_id: id(5),
      robot_id: id(6),
      mentions: []
    })
    // A focus with no trail is still a focus; an empty pin list is nothing to say.
    expect(bodies[1].focus).toEqual({ entity_id: id(7), path: [] })
    for (const body of bodies.slice(2)) {
      for (const key of ['focus', 'pins', 'finding_id', 'robot_id']) {
        expect(body).not.toHaveProperty(key)
      }
    }
  })
}

function messageRequestAuthorizationTests(WIRE: string): void {
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
}

it('cancels artifact streams before buffering beyond the requested bound', async () => {
  const cancel = vi.fn()
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(5))
      },
      cancel
    })
  )
  await expect(
    fetchArtifactBlob('p', 'a', {
      fetchImpl: vi.fn(async () => response),
      getToken: async () => null,
      maxBytes: 4
    })
  ).rejects.toThrow(/bound/)
  expect(cancel).toHaveBeenCalled()
})

it('sends explicit force_confirmation only for confirmation-required turns', async () => {
  const fetchImpl = vi.fn(async () => sseResponse(''))
  const base = {
    projectId: 'p1',
    conversationId: 'c1',
    content: 'Review a file',
    actionMode: 'do' as const,
    onEvent: vi.fn(),
    fetchImpl: fetchImpl as unknown as typeof fetch,
    getToken: async () => null,
    baseUrl: 'http://api.test/api/v1'
  }
  await streamSolMessage({ ...base, forceConfirmation: true })
  await streamSolMessage(base)
  const bodies = fetchImpl.mock.calls.map(
    (call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string) as object
  )
  expect(bodies[0]).toMatchObject({ action_mode: 'do', force_confirmation: true })
  expect(bodies[1]).not.toHaveProperty('force_confirmation')
})

describe('SOLUSDEV-317 resume turns', () => {
  const base = {
    projectId: 'p1',
    conversationId: 'c1',
    actionMode: 'do' as const,
    onEvent: vi.fn(),
    getToken: async () => null,
    baseUrl: 'http://api.test/api/v1'
  }

  it('sends resume_confirmation_id and omits empty content', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(''))
    await streamSolMessage({
      ...base,
      content: '',
      resumeConfirmationId: 'cf-1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const body = JSON.parse(
      (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string
    ) as Record<string, unknown>
    expect(body).toMatchObject({ resume_confirmation_id: 'cf-1', action_mode: 'do' })
    expect(body).not.toHaveProperty('content')
  })

  it('never sends resume_confirmation_id on a normal message', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(''))
    await streamSolMessage({
      ...base,
      content: 'hi',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const body = JSON.parse(
      (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string
    ) as Record<string, unknown>
    expect(body).toMatchObject({ content: 'hi' })
    expect(body).not.toHaveProperty('resume_confirmation_id')
  })

  it('sends a wake turn as process_prompt alone — no content, mentions or resume (§11.2)', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(''))
    await streamSolMessage({
      ...base,
      content: '',
      processPrompt: { processId: 'pr-1', promptSeq: 2 },
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const body = JSON.parse(
      (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string
    ) as Record<string, unknown>
    expect(body).toEqual({
      process_prompt: { process_id: 'pr-1', prompt_seq: 2 },
      action_mode: 'do'
    })
  })

  it('keeps the envelope error code of a refused turn', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: 'resume_limit', message: 'wait' } }), {
          status: 409
        })
    )
    await expect(
      streamSolMessage({
        ...base,
        content: '',
        resumeConfirmationId: 'cf-1',
        fetchImpl: fetchImpl as unknown as typeof fetch
      })
    ).rejects.toMatchObject({ status: 409, code: 'resume_limit' })
  })

  it('falls back to sol_stream_failed for a body without an envelope', async () => {
    const fetchImpl = vi.fn(async () => new Response('<html>', { status: 502 }))
    await expect(
      streamSolMessage({ ...base, content: 'x', fetchImpl: fetchImpl as unknown as typeof fetch })
    ).rejects.toMatchObject({ status: 502, code: 'sol_stream_failed' })
  })
})

describe('SOLUSDEV-319 slice 4 front_app', () => {
  const base = {
    projectId: 'p1',
    conversationId: 'c1',
    actionMode: 'do' as const,
    onEvent: vi.fn(),
    getToken: async () => null,
    baseUrl: 'http://api.test/api/v1'
  }
  const FREECAD = {
    drivable: true as const,
    binding: 'window' as const,
    bundleId: 'org.freecad.FreeCAD',
    name: 'FreeCAD',
    pid: 4242,
    windowId: 77,
    title: 'bracket_v3.FCStd'
  }
  const WIRE_FREECAD = {
    bundle_id: 'org.freecad.FreeCAD',
    name: 'FreeCAD',
    title: 'bracket_v3.FCStd',
    pid: 4242,
    window_id: 77,
    drivable: true,
    binding: 'window'
  }

  async function bodyOf(
    input: Partial<Parameters<typeof streamSolMessage>[0]>
  ): Promise<Record<string, unknown>> {
    const fetchImpl = vi.fn(async () => sseResponse(''))
    await streamSolMessage({
      ...base,
      content: 'add a fillet',
      ...input,
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    return JSON.parse(
      (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string
    ) as Record<string, unknown>
  }

  it('a Build turn from the pill carries the snapshot with every key', async () => {
    expect((await bodyOf({ frontApp: FREECAD })).front_app).toEqual(WIRE_FREECAD)
  })

  it('a denied app is sent with explicit nulls', async () => {
    const body = await bodyOf({
      frontApp: { drivable: false, binding: null, bundleId: 'com.apple.mail', name: 'Mail' }
    })
    expect(body.front_app).toEqual({
      bundle_id: 'com.apple.mail',
      name: 'Mail',
      title: null,
      pid: null,
      window_id: null,
      drivable: false,
      binding: null
    })
  })

  it('omits front_app with no snapshot, and in Guide mode', async () => {
    expect(await bodyOf({ frontApp: null })).not.toHaveProperty('front_app')
    expect(await bodyOf({ frontApp: FREECAD, actionMode: 'guide' })).not.toHaveProperty('front_app')
  })

  it('never sends front_app on a resume or a wake turn', async () => {
    const resume = await bodyOf({ content: '', resumeConfirmationId: 'cf-1', frontApp: FREECAD })
    expect(resume).not.toHaveProperty('front_app')
    const wake = await bodyOf({
      content: '',
      processPrompt: { processId: 'pr-1', promptSeq: 2 },
      frontApp: FREECAD
    })
    expect(wake).not.toHaveProperty('front_app')
  })

  it('reads the pill’s snapshot from the SOL window store when not given', async () => {
    const { useSolWindowStore } = await import('./solWindowStore')
    useSolWindowStore.setState({ frontApp: FREECAD })
    try {
      expect((await bodyOf({})).front_app).toEqual(WIRE_FREECAD)
    } finally {
      useSolWindowStore.setState({ frontApp: null })
    }
    expect(await bodyOf({})).not.toHaveProperty('front_app')
  })
})
