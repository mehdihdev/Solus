// The pure transcript-item helpers split out of solChatStore.ts.
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { ChatItem } from './solChatStore'
import {
  MAX_TURN_CHARS,
  appendContent,
  applyEvent,
  blankItem,
  turnFailureText
} from './solChatItems'

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
