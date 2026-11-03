// The pure transcript-item helpers split out of solChatStore.ts.
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { SolTurn } from './solApi'
import type { ChatItem } from './solChatStore'
import {
  MAX_TURN_CHARS,
  appendContent,
  applyEvent,
  applyReasoningFrame,
  blankItem,
  turnFailureText,
  turnToReasonedItem,
  type Patch
} from './solChatItems'
import type { SolStreamEvent } from './solStream'

function patcher(start: ChatItem): {
  patch: (fn: (item: ChatItem) => ChatItem) => void
  item: () => ChatItem
} {
  let current = start
  return { patch: (fn) => (current = fn(current)), item: () => current }
}

describe('solChatItems', () => {
  it('caps appended content at MAX_TURN_CHARS', () => {
    const p = patcher(blankItem('a', 'assistant', 'x'.repeat(MAX_TURN_CHARS - 1)))
    appendContent(p.patch, 'yyy')
    expect(p.item().content).toHaveLength(MAX_TURN_CHARS)
    appendContent(p.patch, 'z')
    expect(p.item().content).toHaveLength(MAX_TURN_CHARS)
  })

  it('does not duplicate a re-sent confirmation card', () => {
    const p = patcher(blankItem('a', 'assistant', ''))
    const pending = { confirmationId: 'c1', tool: 'code.exec', summary: 's', preview: [] }
    applyEvent(p.patch, { type: 'tool_confirmation', pending })
    applyEvent(p.patch, { type: 'tool_confirmation', pending })
    expect(p.item().confirmations).toHaveLength(1)
  })

  it('maps credit and rate-limit failures to author-safe text', () => {
    expect(turnFailureText(new ApiError(402, 'x', 'raw'))).toMatch(/credits/)
    expect(turnFailureText(new ApiError(429, 'x', 'raw'))).toMatch(/Too many/)
    expect(turnFailureText(new Error('secret detail'))).toBe('SOL is unreachable right now.')
  })

  it('appends an auto-run row once per call, immutably', () => {
    const before = blankItem('a', 'assistant', '')
    const { patch, item } = patcher(before)
    const autoRun = { callId: 'c1', program: 'ls', status: 'exited 0', output: 'x' }
    const event = { type: 'tool_result' as const, callId: 'c1', ok: true, errorCode: null, autoRun }
    applyEvent(patch, event)
    applyEvent(patch, event)
    expect(item().autoRuns).toEqual([autoRun])
    expect(before.autoRuns).toBeUndefined()
  })
})

// SOLUSDEV-321 P1-T6: the frames that say how an answer was reached land on the assistant item
// that streamed them. A separate pass after `applyEvent`: that switch is already at the
// complexity limit, so two more cases would not lint.
describe('applyReasoningFrame', () => {
  const fresh = (): ReturnType<typeof patcher> => patcher(blankItem('a1', 'assistant', '', true))

  it('puts the tier that answered on the assistant item', () => {
    const { patch, item } = fresh()
    applyReasoningFrame(patch, {
      type: 'answer_source',
      answer: { source: 'graph', sources: ['config'] }
    })
    expect(item().answerSource).toEqual({ source: 'graph', sources: ['config'] })
    expect(item().budgetReached).toBeUndefined()
  })

  it('puts the ceiling the turn reached on the assistant item', () => {
    const { patch, item } = fresh()
    applyReasoningFrame(patch, {
      type: 'budget_reached',
      budget: { limit: 'tool_calls', used: 24, cap: 24 }
    })
    expect(item().budgetReached).toEqual({ limit: 'tool_calls', used: 24, cap: 24 })
    expect(item().answerSource).toBeUndefined()
  })

  it('hangs a call’s args on its own trace step, by call id', () => {
    const { patch, item } = fresh()
    for (const callId of ['k1', 'k2']) {
      applyEvent(patch, { type: 'tool_call', callId, tool: 'get_entity' })
    }
    applyReasoningFrame(patch, {
      type: 'tool_call',
      callId: 'k2',
      tool: 'get_entity',
      args: { entity_id: 'imu', password: '[REDACTED]' }
    })
    expect(item().trace.map((step) => step.args)).toEqual([
      undefined,
      { entity_id: 'imu', password: '[REDACTED]' }
    ])
    // The step itself is untouched.
    expect(item().trace[1]).toMatchObject({ callId: 'k2', tool: 'get_entity', ok: null })
  })

  it('leaves the item alone for a call with no args and for every other frame', () => {
    const { patch, item } = fresh()
    applyEvent(patch, { type: 'tool_call', callId: 'k1', tool: 'get_entity' })
    const before = item()
    applyReasoningFrame(patch, { type: 'tool_call', callId: 'k1', tool: 'get_entity' })
    applyReasoningFrame(patch, { type: 'token', text: 'hi' })
    applyReasoningFrame(patch, { type: 'done', conversationId: 'c1', turnId: 't1' })
    expect(item()).toBe(before)
  })
})

// SOLUSDEV-321 P7: a round's reasoning streams before the calls it precedes, so it waits on the
// item until the proposal card arrives, then hangs on that card — and only on that one.
describe('applyReasoningFrame — a proposal’s reasoning', () => {
  const fresh = (): ReturnType<typeof patcher> => patcher(blankItem('a1', 'assistant', '', true))
  const reasoning = {
    considered: ['raise the lid 2 mm'],
    ruledOut: [{ what: 'a thinner wall', why: 'under the print minimum' }],
    proposing: 'Set WIDTH to 120 mm.'
  }
  const card = (confirmationId: string): SolStreamEvent => ({
    type: 'tool_confirmation',
    pending: { confirmationId, tool: 'onshape.set_variable', summary: 's', preview: [] }
  })
  const land = (patch: Patch, event: SolStreamEvent): void => {
    applyEvent(patch, event)
    applyReasoningFrame(patch, event)
  }

  it('hangs a round’s reasoning on the proposal card that follows it, and on no later card', () => {
    const { patch, item } = fresh()
    land(patch, { type: 'reasoning', reasoning })
    expect(item().reasoning).toEqual([{ confirmationId: null, reasoning }])
    land(patch, card('cf1'))
    expect(item().reasoning).toEqual([{ confirmationId: 'cf1', reasoning }])
    land(patch, card('cf2'))
    expect(item().reasoning).toEqual([{ confirmationId: 'cf1', reasoning }])
  })

  it('lets a newer round’s reasoning replace one still waiting, and keeps the cards’ own', () => {
    const { patch, item } = fresh()
    const later = { ...reasoning, proposing: 'Move the port instead.' }
    land(patch, { type: 'reasoning', reasoning })
    land(patch, card('cf1'))
    land(patch, { type: 'reasoning', reasoning: { ...reasoning, proposing: 'stale' } })
    land(patch, { type: 'reasoning', reasoning: later })
    land(patch, card('cf2'))
    expect(item().reasoning).toEqual([
      { confirmationId: 'cf1', reasoning },
      { confirmationId: 'cf2', reasoning: later }
    ])
  })

  it('leaves the item as it is when a card arrives with no reasoning waiting', () => {
    const { patch, item } = fresh()
    applyEvent(patch, card('cf1'))
    const before = item()
    applyReasoningFrame(patch, card('cf1'))
    expect(item()).toBe(before)
  })
})

describe('turnToReasonedItem', () => {
  const turn = (role: SolTurn['role'], attrs: SolTurn['attrs']): SolTurn => ({
    id: 't1',
    conversation_id: 'c1',
    role,
    content: 'The IMU is at 0x4A.',
    attrs,
    created_at: ''
  })

  it('reads the stored answer source and budget ceiling back onto the item', () => {
    const item = turnToReasonedItem(
      turn('assistant', {
        answer_source: 'graph',
        sources: ['config', 'telemetry'],
        citations: ['[config:imu]'],
        budget_reached: { limit: 'web_searches', used: 1, cap: 1 }
      })
    )
    expect(item.answerSource).toEqual({ source: 'graph', sources: ['config', 'telemetry'] })
    expect(item.budgetReached).toEqual({ limit: 'web_searches', used: 1, cap: 1 })
    expect(item).toMatchObject({ id: 't1', role: 'assistant', content: 'The IMU is at 0x4A.' })
  })

  it('reads a stored answer source that carries no fact sources as none', () => {
    const item = turnToReasonedItem(turn('assistant', { answer_source: 'graph' }))
    expect(item.answerSource).toEqual({ source: 'graph', sources: [] })
  })

  it('keeps the research sources the earlier reader already attached', () => {
    const item = turnToReasonedItem(
      turn('assistant', {
        research_sources: {
          call_id: 'c1',
          question: 'OV9281 supply',
          cached: false,
          searches: 1,
          pages: 1,
          sources: [{ url: 'https://docs.example.com/ov9281', title: 'OV9281', fetched: true }]
        }
      })
    )
    expect(item.researchSources?.sources).toHaveLength(1)
    expect(item.answerSource).toBeUndefined()
  })

  it('shows nothing it cannot prove — a malformed stored value is left off, not half shown', () => {
    const item = turnToReasonedItem(
      turn('assistant', {
        answer_source: 7,
        sources: ['config'],
        budget_reached: { limit: 'tool_calls', used: -1, cap: 24 }
      })
    )
    expect(item).not.toHaveProperty('answerSource')
    expect(item).not.toHaveProperty('budgetReached')
  })

  it('adds neither key to a turn that carries no such attrs', () => {
    const item = turnToReasonedItem(turn('user', {}))
    expect(item).not.toHaveProperty('answerSource')
    expect(item).not.toHaveProperty('budgetReached')
  })
})
