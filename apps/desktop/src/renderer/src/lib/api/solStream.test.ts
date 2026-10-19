// SOL SSE stream parsing. The interesting behaviour is chunk boundaries —
// network chunks do not align with frames — so the parser is pure and tested
// without a network.
import { describe, expect, it, vi } from 'vitest'
import {
  AUTO_RUN_TAIL_CHARS,
  joinTails,
  parseSseBuffer,
  parseSseFrame,
  streamSolTurn,
  toAutoRun,
  toPendingConfirmation,
  toSolArtifact,
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

// SOLUSDEV-252 S5: a tool's large/binary output arrives as an `artifact` frame
// (docs/contracts/agent-tool.md §4). The payload crosses a process boundary,
// so anything that cannot prove the ArtifactRef shape is dropped.
describe('toSolArtifact', () => {
  const DATA = {
    artifact_id: 'a1',
    uri: '/api/v1/projects/p1/artifacts/a1/content',
    media_type: 'image/svg+xml',
    title: 'Power tree',
    source_tool: 'solus.make_diagram',
    summary: 'Battery → regulators → loads'
  }

  it('reads the reference verbatim', () => {
    expect(toSolArtifact({ type: 'artifact', data: DATA })).toEqual({
      artifactId: 'a1',
      uri: '/api/v1/projects/p1/artifacts/a1/content',
      mediaType: 'image/svg+xml',
      title: 'Power tree',
      sourceTool: 'solus.make_diagram',
      summary: 'Battery → regulators → loads'
    })
  })

  it('falls back to the tool name, then a generic title, when no title is sent', () => {
    const noTitle = { ...DATA, title: undefined }
    expect(toSolArtifact({ type: 'artifact', data: noTitle })?.title).toBe('solus.make_diagram')
    const bare = { ...noTitle, source_tool: undefined }
    expect(toSolArtifact({ type: 'artifact', data: bare })?.title).toBe('Artifact')
  })

  it('returns null without an id, uri or media type', () => {
    expect(toSolArtifact({ type: 'artifact', data: { ...DATA, artifact_id: 7 } })).toBeNull()
    expect(toSolArtifact({ type: 'artifact', data: { ...DATA, uri: null } })).toBeNull()
    expect(toSolArtifact({ type: 'artifact', data: { ...DATA, media_type: undefined } })).toBeNull()
  })

  it('treats a non-string summary or source_tool as absent, never as text', () => {
    const artifact = toSolArtifact({
      type: 'artifact',
      data: { ...DATA, summary: { evil: true }, source_tool: 12 }
    })
    expect(artifact?.summary).toBeNull()
    expect(artifact?.sourceTool).toBeNull()
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

// SOLUSDEV-317 follow-up (code-command-execution.md §10.1/§10.3): a Build-mode
// code.exec that ran without a card arrives on its tool_result frame.
describe('toAutoRun', () => {
  const base = {
    call_id: 'c9',
    ok: true,
    tool: 'code.exec',
    auto: true,
    program: '/bin/ls',
    status: 'exited 0',
    stdout_tail: 'a\nb\n',
    stderr_tail: 'warn'
  }

  it('reads the auto-run fields into a row: basename, status, stdout then stderr', () => {
    expect(toAutoRun(base)).toEqual({
      callId: 'c9',
      program: 'ls',
      status: 'exited 0',
      output: 'a\nb\nwarn'
    })
  })

  it('treats absent tails as no output', () => {
    const rest = { ...base, program: 'colcon', stdout_tail: undefined, stderr_tail: undefined }
    expect(toAutoRun(rest)?.output).toBe('')
  })

  it.each([
    ['not auto', { auto: false }],
    ['auto not literally true', { auto: 'true' }],
    ['another tool', { tool: 'code.run' }],
    ['no program', { program: undefined }],
    ['empty program', { program: '' }],
    ['no status', { status: undefined }],
    ['numeric status', { status: 0 }],
    ['junk tail', { stdout_tail: ['x'] }],
    ['no call id', { call_id: 3 }]
  ])('yields no row when %s', (_name, over) => {
    expect(toAutoRun({ ...base, ...over })).toBeNull()
  })

  it('bounds every field', () => {
    const row = toAutoRun({
      ...base,
      program: `/x/${'p'.repeat(5000)}`,
      status: 's'.repeat(5000),
      stdout_tail: 'o'.repeat(AUTO_RUN_TAIL_CHARS * 2)
    })
    expect(row?.program.length).toBeLessThanOrEqual(256)
    expect(row?.status.length).toBeLessThanOrEqual(200)
    expect(row?.output.length).toBeLessThanOrEqual(AUTO_RUN_TAIL_CHARS * 2 + 1)
  })

  it('joins tails with a newline only when stdout lacks one', () => {
    expect(joinTails('a', 'b')).toBe('a\nb')
    expect(joinTails('a\n', 'b')).toBe('a\nb')
    expect(joinTails('', 'b')).toBe('b')
    expect(joinTails('a', '')).toBe('a')
  })
})
