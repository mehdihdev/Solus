// SOLUSDEV-326: SOL's thought summary on a transcript item — pure helpers.
import { describe, expect, it } from 'vitest'
import { blankItem } from './solChatItems'
import {
  addThought,
  humanizeTool,
  replyGrowth,
  MAX_THINKING_CHARS,
  thoughtSummary,
  toThinkingInfo
} from './thinking'

const item = () => blankItem('a1', 'assistant', '', true)

describe('addThought', () => {
  it('starts a segment, then appends to it while no tool step has started', () => {
    const once = addThought(item(), 'Check the ', 1_000)
    const twice = addThought(once, 'bus.', 1_400)

    expect(twice.thinking).toEqual({
      segments: [{ text: 'Check the bus.', afterSteps: 0 }],
      lastAt: 1_400,
      ms: 400
    })
  })

  it('opens a new segment after a tool step, placed after that step', () => {
    const first = addThought(item(), 'Look it up.', 0)
    const stepped = {
      ...first,
      trace: [{ callId: 'c1', tool: 'graph.get_entity', ok: true, errorCode: null }]
    }

    const next = addThought(stepped, 'Now answer.', 2_000)

    expect(next.thinking?.segments).toEqual([
      { text: 'Look it up.', afterSteps: 0 },
      { text: 'Now answer.', afterSteps: 1 }
    ])
  })

  it('counts only the time inside segments, not the tool run between them', () => {
    let current = addThought(item(), 'One ', 0)
    current = addThought(current, 'two.', 2_000)
    current = {
      ...current,
      trace: [{ callId: 'c1', tool: 'graph.get_entity', ok: true, errorCode: null }]
    }
    current = addThought(current, 'Three ', 50_000)
    current = addThought(current, 'four.', 51_500)

    expect(current.thinking?.ms).toBe(3_500)
  })

  it('stops growing at the turn cap', () => {
    let current = item()
    for (let i = 0; i < 40; i++) current = addThought(current, 'x'.repeat(1_000), i)

    const total = current.thinking!.segments.reduce((n, s) => n + s.text.length, 0)
    expect(total).toBe(MAX_THINKING_CHARS)
  })

  it('never mutates the item it is given', () => {
    const before = item()
    addThought(before, 'hmm', 0)
    expect(before.thinking).toBeUndefined()
  })
})

describe('toThinkingInfo (a reloaded turn’s attrs.thinking)', () => {
  it('reads segments and duration', () => {
    expect(toThinkingInfo({ segments: ['One.', 'Two.'], ms: 2_500 })).toEqual({
      segments: [
        { text: 'One.', afterSteps: 0 },
        { text: 'Two.', afterSteps: 0 }
      ],
      lastAt: null,
      ms: 2_500
    })
  })

  it('places each stored segment after the steps that preceded it', () => {
    expect(toThinkingInfo({ segments: ['One.', 'Two.'], after: [0, 3], ms: 10 })?.segments).toEqual(
      [
        { text: 'One.', afterSteps: 0 },
        { text: 'Two.', afterSteps: 3 }
      ]
    )
  })

  it('ignores a placement list it cannot prove, and keeps the thought', () => {
    for (const after of [[0], ['x', 1], [-1, 0], [0.5, 1]]) {
      expect(
        toThinkingInfo({ segments: ['One.', 'Two.'], after, ms: 10 })?.segments.map(
          (s) => s.afterSteps
        )
      ).toEqual([0, 0])
    }
  })

  it.each([
    ['not an object', 'nope'],
    ['segments missing', { ms: 1 }],
    ['a non-string segment', { segments: [1], ms: 1 }],
    ['a negative duration', { segments: ['a'], ms: -1 }],
    ['an empty list', { segments: [], ms: 1 }],
    ['too many characters', { segments: ['x'.repeat(MAX_THINKING_CHARS + 1)], ms: 1 }],
    ['too many segments', { segments: Array.from({ length: 201 }, () => 'a'), ms: 1 }]
  ])('rejects %s', (_label, value) => {
    expect(toThinkingInfo(value)).toBeNull()
  })
})

describe('humanizeTool', () => {
  it.each([
    ['graph.get_entity', 'Get entity'],
    ['kicad.read_netlist', 'Read netlist'],
    ['research', 'Research'],
    ['code.exec', 'Exec'],
    ['', 'Tool']
  ])('%s → %s', (tool, label) => {
    expect(humanizeTool(tool)).toBe(label)
  })
})

describe('thoughtSummary', () => {
  it('names the time and the steps', () => {
    expect(thoughtSummary({ segments: [], lastAt: 0, ms: 12_400 }, 3)).toBe(
      'Thought for 12s · 3 steps'
    )
  })

  it('says a few seconds under one second, and one step in the singular', () => {
    expect(thoughtSummary({ segments: [], lastAt: 0, ms: 300 }, 1)).toBe(
      'Thought for a few seconds · 1 step'
    )
  })

  it('falls back to the step count alone when there was no thought', () => {
    expect(thoughtSummary(undefined, 2)).toBe('2 steps')
  })

  it('omits the steps when there were none', () => {
    expect(thoughtSummary({ segments: [], lastAt: 0, ms: 65_000 }, 0)).toBe('Thought for 1m 5s')
  })
})

describe('replyGrowth (what the chat follows while a reply streams)', () => {
  it('grows with the thought and with each step, not only the text', () => {
    const empty = item()
    const thought = addThought(empty, 'Checking the bus.', 0)
    const stepped = {
      ...thought,
      trace: [{ callId: 'c1', tool: 'graph.get_entity', ok: null, errorCode: null }]
    }
    const finished = {
      ...stepped,
      trace: [{ callId: 'c1', tool: 'graph.get_entity', ok: true, errorCode: null }]
    }

    expect(replyGrowth(thought)).toBeGreaterThan(replyGrowth(empty))
    expect(replyGrowth(stepped)).toBeGreaterThan(replyGrowth(thought))
    expect(replyGrowth(finished)).toBeGreaterThan(replyGrowth(stepped))
    expect(replyGrowth({ ...finished, content: 'Answer' })).toBeGreaterThan(replyGrowth(finished))
  })
})
