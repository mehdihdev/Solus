// SOLX-02: pure SSE framing for the SOL turn stream (POST …/messages).
// Feed chunks, get validated events — no network, no timers. Malformed or
// unknown frames are dropped at the boundary (CLAUDE.md §7: parse defensively).
import { describe, it, expect } from 'vitest'
import { createSolStreamParser, type SolStreamEvent } from './solStream'

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

describe('solStream framing', () => {
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
      { type: 'tool_call', callId: 'c1', tool: 'get_entity' },
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

  it('never retains tool args — the frame carries name + correlation only', () => {
    const parser = createSolStreamParser()
    const [event] = parser.push(
      frame('tool_call', { call_id: 'c9', tool: 'flash', args: { secret: 'hunter2' } })
    )
    expect(event).toEqual({ type: 'tool_call', callId: 'c9', tool: 'flash' })
    expect(JSON.stringify(event)).not.toContain('hunter2')
  })

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
})
