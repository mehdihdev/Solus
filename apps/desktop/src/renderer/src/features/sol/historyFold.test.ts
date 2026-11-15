// SOLUSDEV-326: a reloaded turn reads like the live one — the tool rows stored before a reply fold
// into that reply's steps (its Thinking block) instead of a column of grey `tool → ok` lines.
import { describe, expect, it } from 'vitest'
import { foldToolTurns } from './historyFold'
import type { SolTurn } from './solApi'

const turn = (id: string, role: SolTurn['role'], content: string, attrs = {}): SolTurn => ({
  id,
  conversation_id: 'c1',
  role,
  content,
  attrs,
  created_at: '2026-11-14T00:00:00Z'
})

const toolTurn = (id: string, tool: string, ok: boolean, args: object = {}): SolTurn =>
  turn(id, 'tool', `${tool} → ${ok ? 'ok' : 'timeout'}`, {
    call: { call_id: `call-${id}`, tool, args },
    result: {
      call_id: `call-${id}`,
      ok,
      ...(ok ? {} : { error: { code: 'TIMEOUT', message: 'x' } })
    }
  })

describe('foldToolTurns', () => {
  it('folds the tool rows before a reply into that reply’s steps, in order', () => {
    const items = foldToolTurns([
      turn('u1', 'user', 'why?'),
      toolTurn('t1', 'graph.search_workspace', true, { q: 'I2C' }),
      toolTurn('t2', 'kicad.read_netlist', false),
      turn('a1', 'assistant', 'Because.')
    ])

    expect(items.map((i) => i.role)).toEqual(['user', 'assistant'])
    expect(items[1].trace).toEqual([
      {
        callId: 'call-t1',
        tool: 'graph.search_workspace',
        ok: true,
        errorCode: null,
        args: { q: 'I2C' }
      },
      { callId: 'call-t2', tool: 'kicad.read_netlist', ok: false, errorCode: 'TIMEOUT' }
    ])
  })

  it('keeps each reply’s own steps apart', () => {
    const items = foldToolTurns([
      toolTurn('t1', 'a.one', true),
      turn('a1', 'assistant', 'One.'),
      turn('u2', 'user', 'and?'),
      toolTurn('t2', 'a.two', true),
      turn('a2', 'assistant', 'Two.')
    ])

    expect(items.filter((i) => i.role === 'assistant').map((i) => i.trace.length)).toEqual([1, 1])
  })

  it('leaves tool rows with no reply after them as rows (an aborted turn)', () => {
    const items = foldToolTurns([toolTurn('t1', 'a.one', true), turn('u2', 'user', 'hello?')])

    expect(items.map((i) => i.role)).toEqual(['tool', 'user'])
  })

  it('leaves a row whose stored attrs are unproven as a row, never a made-up step', () => {
    const items = foldToolTurns([
      turn('t1', 'tool', 'odd → ok', { call: { tool: 42 } }),
      turn('a1', 'assistant', 'Done.')
    ])

    expect(items.map((i) => i.role)).toEqual(['tool', 'assistant'])
    expect(items[1].trace).toEqual([])
  })

  it('still reads the reply’s stored thought', () => {
    const items = foldToolTurns([
      toolTurn('t1', 'a.one', true),
      turn('a1', 'assistant', 'Done.', {
        thinking: { segments: ['Look.', 'Then.'], after: [0, 1], ms: 900 }
      })
    ])

    expect(items[0].thinking?.segments).toEqual([
      { text: 'Look.', afterSteps: 0 },
      { text: 'Then.', afterSteps: 1 }
    ])
  })
})
