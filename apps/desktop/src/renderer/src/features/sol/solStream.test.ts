// SOLX-02: pure SSE framing for the SOL turn stream (POST …/messages).
// Feed chunks, get validated events — no network, no timers. Malformed or
// unknown frames are dropped at the boundary (CLAUDE.md §7: parse defensively).
import { describe, it, expect } from 'vitest'
import { createSolStreamParser, type SolStreamEvent } from './solStream'

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

describe('solStream framing', () => {
  streamMessageFramesTests()
  streamArtifactFramesTests()
  streamErrorValidationTests()
  streamFramingBoundariesTests()
})

describe('context_used frame (SOLUSDEV-233)', () => {
  it('parses the turn context manifest', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      frame('context_used', {
        sections: [
          { kind: 'graph', citation: '[graph:motor_driver]', tokens: 120 },
          { kind: 'document', citation: '[datasheet:so101.urdf]', tokens: 300 },
          { kind: 'telemetry', citation: null, tokens: 40 }
        ],
        truncated: false,
        dropped: 2
      })
    )
    expect(events).toEqual([
      {
        type: 'context_used',
        sections: [
          { kind: 'graph', citation: '[graph:motor_driver]', tokens: 120 },
          { kind: 'document', citation: '[datasheet:so101.urdf]', tokens: 300 },
          { kind: 'telemetry', citation: null, tokens: 40 }
        ],
        truncated: false,
        dropped: 2
      }
    ])
  })

  it('drops a manifest whose sections are malformed', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      frame('context_used', { sections: [{ kind: 7 }], truncated: false, dropped: 0 })
    )
    expect(events).toEqual([])
  })
})

function streamMessageFramesTests(): void {
  it('parses token, tool frames, message with citations, and done', () => {
    const parser = createSolStreamParser()
    const events: SolStreamEvent[] = []
    const wire =
      frame('token', { text: 'The ' }) +
      frame('token', { text: 'IMU…' }) +
      frame('tool_call', { call_id: 'c1', tool: 'get_entity', args: { key: 'imu' } }) +
      frame('tool_result', { call_id: 'c1', ok: true, value: { id: 'e1' } }) +
      frame('message', {
        role: 'assistant',
        content: 'The IMU shares the bus.',
        citations: ['entity:imu_bno085', 'relation:i2c0']
      }) +
      frame('done', { conversation_id: 'conv1', turn_id: 't1' })
    // Deliver in awkward chunks to prove framing survives chunk boundaries.
    for (let i = 0; i < wire.length; i += 7) {
      events.push(...parser.push(wire.slice(i, i + 7)))
    }
    expect(events).toEqual([
      { type: 'token', text: 'The ' },
      { type: 'token', text: 'IMU…' },
      { type: 'tool_call', callId: 'c1', tool: 'get_entity', args: { key: 'imu' } },
      { type: 'tool_result', callId: 'c1', ok: true, errorCode: null },
      {
        type: 'message',
        role: 'assistant',
        content: 'The IMU shares the bus.',
        citations: ['entity:imu_bno085', 'relation:i2c0']
      },
      { type: 'done', conversationId: 'conv1', turnId: 't1' }
    ])
  })

  // SOLUSDEV-321 P1-T6: the args come back, but only as the server masked them — agent/stream.py
  // runs them through redact_value before the frame leaves (SOLX-04 SEC-H3), so a secret-named
  // key arrives as [REDACTED] and its value never crosses the wire (pinned server-side in
  // packages/api/tests/test_stream.py). The desktop adds the bound: every value is cut to 64
  // characters, ellipsis included, and kept as the literal text it was.
  it('retains only REDACTED tool args — the masked value stays masked, every value bounded', () => {
    const parser = createSolStreamParser()
    const [event] = parser.push(
      frame('tool_call', {
        call_id: 'c9',
        tool: 'flash',
        args: {
          port: '/dev/ttyUSB0',
          secret: '[REDACTED]',
          note: 'n'.repeat(100),
          markup: '<b>x</b>'
        }
      })
    )
    expect(event).toEqual({
      type: 'tool_call',
      callId: 'c9',
      tool: 'flash',
      args: {
        port: '/dev/ttyUSB0',
        secret: '[REDACTED]',
        note: `${'n'.repeat(63)}…`,
        markup: '<b>x</b>'
      }
    })
  })
}

function streamArtifactFramesTests(): void {
  it('parses an artifact frame into a validated reference (SOLUSDEV-252 S5)', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      frame('artifact', {
        artifact_id: 'a1',
        uri: '/api/v1/projects/p1/artifacts/a1/content',
        media_type: 'image/svg+xml',
        title: 'Power tree',
        source_tool: 'solus.make_diagram',
        summary: null
      })
    )
    expect(events).toEqual([
      {
        type: 'artifact',
        artifact: {
          artifactId: 'a1',
          uri: '/api/v1/projects/p1/artifacts/a1/content',
          mediaType: 'image/svg+xml',
          title: 'Power tree',
          sourceTool: 'solus.make_diagram',
          summary: null
        }
      }
    ])
  })

  it('drops an artifact frame that cannot identify its bytes', () => {
    const parser = createSolStreamParser()
    expect(parser.push(frame('artifact', { title: 'x', media_type: 'image/png' }))).toEqual([])
    expect(parser.push(frame('artifact', { artifact_id: 'a1', uri: '/u' }))).toEqual([])
  })
}

function streamErrorValidationTests(): void {
  it('surfaces the error code of a failed tool result', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      frame('tool_result', { call_id: 'c1', ok: false, error: { code: 'not_found', message: 'x' } })
    )
    expect(events).toEqual([
      { type: 'tool_result', callId: 'c1', ok: false, errorCode: 'not_found' }
    ])
  })

  it('parses the author-safe error frame', () => {
    const parser = createSolStreamParser()
    expect(
      parser.push(frame('error', { code: 'timeout', message: 'The SOL turn timed out.' }))
    ).toEqual([{ type: 'error', code: 'timeout', message: 'The SOL turn timed out.' }])
  })

  it('drops malformed frames: bad JSON, unknown events, wrong field types', () => {
    const parser = createSolStreamParser()
    const events = [
      ...parser.push('event: token\ndata: {not json}\n\n'),
      ...parser.push(frame('exfiltrate', { text: 'hi' })),
      ...parser.push(frame('token', { text: 42 })),
      ...parser.push(frame('tool_call', { call_id: 'c1' })),
      ...parser.push(frame('done', { conversation_id: 'c' })),
      // A frame after garbage still parses — one bad frame must not poison the stream.
      ...parser.push(frame('token', { text: 'ok' }))
    ]
    expect(events).toEqual([{ type: 'token', text: 'ok' }])
  })

  it('drops a message frame whose citations are not a string array (SOL-02: citations are structured, never improvised)', () => {
    const parser = createSolStreamParser()
    const events = [
      ...parser.push(frame('message', { role: 'assistant', content: 'x' })),
      ...parser.push(frame('message', { role: 'assistant', content: 'x', citations: 'entity:a' })),
      ...parser.push(
        frame('message', { role: 'assistant', content: 'x', citations: ['ok', { evil: 1 }] })
      ),
      ...parser.push(frame('message', { role: 'assistant', content: 'x', citations: [] }))
    ]
    expect(events).toEqual([{ type: 'message', role: 'assistant', content: 'x', citations: [] }])
  })
}

function streamFramingBoundariesTests(): void {
  it('tolerates CRLF line endings and SSE comment/id fields', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      ': keepalive\r\nid: 7\r\nevent: token\r\ndata: {"text":"hi"}\r\n\r\n'
    )
    expect(events).toEqual([{ type: 'token', text: 'hi' }])
  })

  // CTR-03 regression: this frame had no validator, so `toEvent` dropped it as
  // unknown and the backend could park a destructive action the user was never
  // shown. The parse boundary is where that failure was invisible.
  it('carries a parked destructive action through, with its diff', () => {
    const parser = createSolStreamParser()
    const events = parser.push(
      frame('tool_confirmation', {
        confirmation_id: 'cf1',
        tool: 'onshape.set_variable',
        summary: 'Set WIDTH to 120 mm',
        preview: [{ label: 'WIDTH', before: '100 mm', after: '120 mm' }]
      })
    )
    expect(events).toEqual([
      {
        type: 'tool_confirmation',
        pending: {
          confirmationId: 'cf1',
          tool: 'onshape.set_variable',
          summary: 'Set WIDTH to 120 mm',
          preview: [{ label: 'WIDTH', before: '100 mm', after: '120 mm' }]
        }
      }
    ])
  })

  it('drops a confirmation with no id rather than rendering an unapprovable prompt', () => {
    const parser = createSolStreamParser()
    expect(parser.push(frame('tool_confirmation', { tool: 'onshape.set_variable' }))).toEqual([])
  })

  it('discards a runaway undelimited buffer instead of growing without bound', () => {
    const parser = createSolStreamParser()
    expect(parser.push('data: '.concat('A'.repeat(2_000_000)))).toEqual([])
    // After the flush, well-formed frames parse again.
    expect(parser.push('\n\n' + frame('token', { text: 'ok' }))).toEqual([
      { type: 'token', text: 'ok' }
    ])
  })
}

describe('auto-run tool_result (SOLUSDEV-317 §10.1)', () => {
  it('carries an auto-run row on the tool_result event', () => {
    const [event] = createSolStreamParser().push(
      frame('tool_result', {
        call_id: 'c1',
        ok: true,
        tool: 'code.exec',
        auto: true,
        program: 'ls',
        status: 'exited 0',
        stdout_tail: 'x\n',
        stderr_tail: ''
      })
    )
    expect(event).toEqual({
      type: 'tool_result',
      callId: 'c1',
      ok: true,
      errorCode: null,
      autoRun: { callId: 'c1', program: 'ls', status: 'exited 0', output: 'x\n' }
    })
  })

  it('keeps a plain tool_result (or a malformed auto payload) row-less', () => {
    const events = createSolStreamParser().push(
      frame('tool_result', { call_id: 'c1', ok: true }) +
        frame('tool_result', { call_id: 'c2', ok: true, auto: true, tool: 'code.exec' })
    )
    expect(events).toEqual([
      { type: 'tool_result', callId: 'c1', ok: true, errorCode: null },
      { type: 'tool_result', callId: 'c2', ok: true, errorCode: null }
    ])
  })
})

describe('research_sources frame (SOLUSDEV-321 P1-T5)', () => {
  const data = {
    call_id: 'c1',
    question: 'OV9281 supply voltage',
    cached: true,
    searches: 0,
    pages: 0,
    sources: [{ url: 'https://docs.example.com/ov9281', title: 'OV9281 datasheet', fetched: true }]
  }

  it('parses into the validated sources, camel-cased, after the tool_result it follows', () => {
    const events = createSolStreamParser().push(
      frame('tool_result', { call_id: 'c1', ok: true, value: { findings: [] } }) +
        frame('research_sources', data)
    )
    expect(events).toEqual([
      { type: 'tool_result', callId: 'c1', ok: true, errorCode: null },
      {
        type: 'research_sources',
        research: {
          callId: 'c1',
          question: 'OV9281 supply voltage',
          cached: true,
          searches: 0,
          pages: 0,
          sources: [
            { url: 'https://docs.example.com/ov9281', title: 'OV9281 datasheet', fetched: true }
          ]
        }
      }
    ])
  })

  it('drops a malformed or oversized frame whole', () => {
    const tooMany = Array.from({ length: 21 }, () => data.sources[0])
    const events = createSolStreamParser().push(
      frame('research_sources', { ...data, sources: 'https://x' }) +
        frame('research_sources', { ...data, sources: tooMany }) +
        frame('research_sources', { ...data, searches: -1 })
    )
    expect(events).toEqual([])
  })
})

const FOCUSED = '0f9c2f2a-1111-4222-8333-444455556666'
const NAMED = '0f9c2f2a-1111-4222-8333-444455557777'
const LOST = '0f9c2f2a-1111-4222-8333-444455558888'
// The server's manifest (agent/context.py Context.manifest): layers in PROMPT order.
const wire = {
  sections: [
    { kind: 'graph', citation: '[graph:motor_driver]', tokens: 120, layer: 'graph' },
    { kind: 'telemetry', citation: null, tokens: 40, layer: 'telemetry' }
  ],
  truncated: false,
  dropped: 0,
  layers: [
    { layer: 'project_card', tokens: 60, sections: 1, empty_reason: null },
    { layer: 'graph', tokens: 120, sections: 1, empty_reason: null },
    { layer: 'screen', tokens: 0, sections: 0, empty_reason: 'no screenshot on this turn' }
  ],
  anchors: [
    { id: FOCUSED, reason: 'focused' },
    { id: NAMED, reason: 'name_match' }
  ],
  anchors_dropped: [{ id: LOST, reason: 'mentioned', cause: 'not_visible' }]
}

describe('context_used layers and anchors (SOLUSDEV-321 P1-T6)', () => {
  it('keeps the layers in the server order, the anchors and the dropped anchors', () => {
    const [event] = createSolStreamParser().push(frame('context_used', wire))
    expect(event).toEqual({
      type: 'context_used',
      sections: [
        { kind: 'graph', citation: '[graph:motor_driver]', tokens: 120, layer: 'graph' },
        { kind: 'telemetry', citation: null, tokens: 40, layer: 'telemetry' }
      ],
      truncated: false,
      dropped: 0,
      layers: [
        { layer: 'project_card', tokens: 60, emptyReason: null },
        { layer: 'graph', tokens: 120, emptyReason: null },
        { layer: 'screen', tokens: 0, emptyReason: 'no screenshot on this turn' }
      ],
      anchors: [
        { id: FOCUSED, reason: 'focused' },
        { id: NAMED, reason: 'name_match' }
      ],
      anchorsDropped: [{ id: LOST, reason: 'mentioned', cause: 'not_visible' }]
    })
  })

  it('keeps a reason or cause it does not know as a string', () => {
    const [event] = createSolStreamParser().push(
      frame('context_used', {
        ...wire,
        anchors: [{ id: FOCUSED, reason: 'a_reason_from_the_future' }],
        anchors_dropped: [{ id: LOST, reason: 'pinned' }]
      })
    )
    expect(event).toMatchObject({
      anchors: [{ id: FOCUSED, reason: 'a_reason_from_the_future' }],
      anchorsDropped: [{ id: LOST, reason: 'pinned', cause: null }]
    })
  })
})

describe('context_used rows it cannot prove (SOLUSDEV-321 P1-T6)', () => {
  it('drops the whole frame when a layer, anchor or dropped anchor row is unproven', () => {
    const bad = [
      { ...wire, layers: [{ layer: 'graph', sections: 1, empty_reason: null }] },
      { ...wire, layers: [{ layer: 7, tokens: 1 }] },
      { ...wire, layers: [{ layer: 'graph', tokens: -1 }] },
      { ...wire, layers: [{ layer: 'graph', tokens: 1, empty_reason: 5 }] },
      { ...wire, layers: 'graph' },
      { ...wire, anchors: [{ id: FOCUSED }] },
      { ...wire, anchors: [{ id: 3, reason: 'focused' }] },
      { ...wire, anchors: [null] },
      { ...wire, anchors_dropped: [{ reason: 'pinned', cause: 'over_cap' }] },
      { ...wire, anchors_dropped: [{ id: LOST, reason: 'pinned', cause: 4 }] }
    ]
    const events = createSolStreamParser().push(bad.map((d) => frame('context_used', d)).join(''))
    expect(events).toEqual([])
  })

  it('bounds every list and label so a hostile frame cannot grow the panel without limit', () => {
    const row = (n: number): { id: string; reason: string } => ({ id: `id-${n}`, reason: 'pinned' })
    const bad = [
      { ...wire, layers: Array.from({ length: 33 }, () => wire.layers[0]) },
      { ...wire, anchors: Array.from({ length: 33 }, (_, n) => row(n)) },
      { ...wire, anchors_dropped: Array.from({ length: 513 }, (_, n) => row(n)) },
      { ...wire, layers: [{ layer: 'x'.repeat(65), tokens: 1 }] },
      { ...wire, layers: [{ layer: 'graph', tokens: 0, empty_reason: 'y'.repeat(201) }] },
      { ...wire, anchors: [{ id: 'z'.repeat(65), reason: 'focused' }] }
    ]
    const events = createSolStreamParser().push(bad.map((d) => frame('context_used', d)).join(''))
    expect(events).toEqual([])
  })
})

describe('answer_source frame (SOLUSDEV-321 P1-T6)', () => {
  it('parses the tier that answered and the fact sources it read', () => {
    const events = createSolStreamParser().push(
      frame('answer_source', {
        source: 'graph',
        sources: ['config', 'telemetry'],
        citations: ['[config:imu_bno085]']
      })
    )
    expect(events).toEqual([
      { type: 'answer_source', answer: { source: 'graph', sources: ['config', 'telemetry'] } }
    ])
  })

  it('keeps a source it does not know as a string — what to show is the badge’s call', () => {
    const [event] = createSolStreamParser().push(
      frame('answer_source', { source: 'a_tier_from_the_future', sources: [] })
    )
    expect(event).toEqual({
      type: 'answer_source',
      answer: { source: 'a_tier_from_the_future', sources: [] }
    })
  })

  // The badge rests on `source` alone; a frame that leaves the fact sources out still says who
  // answered (the server always sends them, but a missing list must not make the badge vanish).
  it('accepts a frame with only a source — the fact sources default to none', () => {
    const events = createSolStreamParser().push(frame('answer_source', { source: 'graph' }))
    expect(events).toEqual([{ type: 'answer_source', answer: { source: 'graph', sources: [] } }])
  })

  it('drops a frame with no source or with a source list that is not bounded strings', () => {
    const tooMany = Array.from({ length: 17 }, () => 'config')
    const events = createSolStreamParser().push(
      frame('answer_source', { sources: ['config'] }) +
        frame('answer_source', { source: '', sources: [] }) +
        frame('answer_source', { source: 7, sources: [] }) +
        frame('answer_source', { source: 'graph', sources: null }) +
        frame('answer_source', { source: 'graph', sources: 'config' }) +
        frame('answer_source', { source: 'graph', sources: ['config', { evil: 1 }] }) +
        frame('answer_source', { source: 'graph', sources: tooMany }) +
        frame('answer_source', { source: 'graph', sources: ['c'.repeat(65)] })
    )
    expect(events).toEqual([])
  })
})

describe('budget_reached frame (SOLUSDEV-321 P1-T6)', () => {
  it('parses which ceiling the turn reached, what it used and the cap', () => {
    const events = createSolStreamParser().push(
      frame('budget_reached', { limit: 'tool_calls', used: 24, cap: 24 })
    )
    expect(events).toEqual([
      { type: 'budget_reached', budget: { limit: 'tool_calls', used: 24, cap: 24 } }
    ])
  })

  it('drops a frame whose limit or counts are not proven', () => {
    const events = createSolStreamParser().push(
      frame('budget_reached', { used: 1, cap: 2 }) +
        frame('budget_reached', { limit: '', used: 1, cap: 2 }) +
        frame('budget_reached', { limit: 'tool_calls', used: -1, cap: 2 }) +
        frame('budget_reached', { limit: 'tool_calls', used: 1.5, cap: 2 }) +
        frame('budget_reached', { limit: 'tool_calls', used: '1', cap: 2 }) +
        frame('budget_reached', { limit: 'tool_calls', used: 1 }) +
        frame('budget_reached', { limit: 'l'.repeat(65), used: 1, cap: 2 })
    )
    expect(events).toEqual([])
  })
})

describe('tool_call args as bounded display text (SOLUSDEV-321 P1-T6)', () => {
  const call = (args: unknown): string =>
    frame('tool_call', { call_id: 'c1', tool: 'get_entity', args })
  const argsOf = (args: unknown): unknown => {
    const [event] = createSolStreamParser().push(call(args))
    return event && event.type === 'tool_call' ? event.args : 'no event'
  }

  it('turns every value into text and cuts it to 64 characters, ellipsis included', () => {
    expect(
      argsOf({
        limit: 5,
        dry_run: false,
        note: null,
        filter: { kind: 'ic' },
        pins: [1, 2],
        path: 'x'.repeat(100)
      })
    ).toEqual({
      limit: '5',
      dry_run: 'false',
      note: 'null',
      filter: '{"kind":"ic"}',
      pins: '[1,2]',
      path: `${'x'.repeat(63)}…`
    })
  })

  it('counts characters, not UTF-16 units — 64 astral characters pass whole, 65 are cut', () => {
    const fits = '😀'.repeat(64)
    expect(argsOf({ a: fits })).toEqual({ a: fits })
    expect(argsOf({ a: '😀'.repeat(65) })).toEqual({ a: `${'😀'.repeat(63)}…` })
  })

  it('cuts a long key the same way and keeps at most 16 entries', () => {
    const many = Object.fromEntries(Array.from({ length: 20 }, (_, n) => [`k${n}`, n]))
    expect(Object.keys(argsOf(many) as object)).toEqual(
      Array.from({ length: 16 }, (_, n) => `k${n}`)
    )
    expect(argsOf({ [`k${'y'.repeat(80)}`]: 1 })).toEqual({ [`k${'y'.repeat(62)}…`]: '1' })
  })

  it('keeps the call but no args when they are not an object or are empty', () => {
    for (const args of [['a'], 'text', null, 7, {}]) {
      const [event] = createSolStreamParser().push(call(args))
      expect(event).toEqual({ type: 'tool_call', callId: 'c1', tool: 'get_entity' })
      expect(event).not.toHaveProperty('args')
    }
  })

  it('keeps a key named __proto__ as plain data, never as a prototype', () => {
    const wire = frame('tool_call', { call_id: 'c1', tool: 't' }).replace(
      '}\n\n',
      ',"args":{"__proto__":{"polluted":true},"ok":"1"}}\n\n'
    )
    const [event] = createSolStreamParser().push(wire)
    const args = (event as { args: Record<string, string> }).args
    expect(Object.getPrototypeOf(args)).toBe(Object.prototype)
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
    expect(args.ok).toBe('1')
    expect(Object.keys(args)).toEqual(['__proto__', 'ok'])
  })
})

// SOLUSDEV-321 P7: what SOL weighed before a proposal. Model text the server parsed out of the
// reply, held to its shape, masked and cut (agent/reasoning_frame.py) — bounded again here, and a
// frame with anything unproven in it is dropped whole, never half drawn.
describe('reasoning frame (SOLUSDEV-321 P7)', () => {
  const block = {
    considered: ['raise the lid 2 mm', 'move the USB-C port'],
    ruled_out: [{ what: 'a thinner wall', why: 'under the print minimum' }],
    proposing: 'Set WIDTH to 120 mm.'
  }
  const parse = (data: unknown): SolStreamEvent[] =>
    createSolStreamParser().push(frame('reasoning', data))

  it('keeps reasoning frame', () => {
    expect(parse(block)).toEqual([
      {
        type: 'reasoning',
        reasoning: {
          considered: ['raise the lid 2 mm', 'move the USB-C port'],
          ruledOut: [{ what: 'a thinner wall', why: 'under the print minimum' }],
          proposing: 'Set WIDTH to 120 mm.'
        }
      }
    ])
  })

  it('keeps a frame at its bounds, counting characters rather than UTF-16 units', () => {
    const full = {
      considered: Array(12).fill('😀'.repeat(200)),
      ruled_out: Array(12).fill({ what: 'w'.repeat(200), why: 'y'.repeat(200) }),
      proposing: 'p'.repeat(400)
    }
    const [event] = parse(full)
    expect(event).toMatchObject({ type: 'reasoning', reasoning: { proposing: 'p'.repeat(400) } })
  })

  it('drops a frame it cannot prove, whole', () => {
    const unproven = [
      { ...block, considered: 'one string' },
      { ...block, considered: [7] },
      { ...block, considered: Array(13).fill('x') },
      { ...block, considered: ['😀'.repeat(201)] },
      { ...block, ruled_out: [{ what: 'a thinner wall' }] },
      { ...block, ruled_out: ['a thinner wall'] },
      { ...block, ruled_out: Array(13).fill({ what: 'x', why: 'y' }) },
      { ...block, proposing: 'x'.repeat(401) },
      { ...block, proposing: 7 },
      { considered: [], ruled_out: [] }
    ]
    for (const data of unproven) expect(parse(data)).toEqual([])
  })
})
