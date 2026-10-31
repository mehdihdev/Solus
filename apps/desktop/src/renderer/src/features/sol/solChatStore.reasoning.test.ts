// SOLUSDEV-321 P1-T6: the frames that say how an answer was reached, through the store's own turn
// path (handleTurnEvent -> applyEvent, then applyReasoningFrame) and read back from a stored turn
// on a reload. Split from solChatStore.test.ts to keep that file under the line cap; the pure
// appliers have their unit tests in solChatItems.test.ts.
import { act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import {
  resetSolChatSessions,
  selectSession,
  sendMessage,
  syncSession,
  useSolChatStore
} from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import type { SolStreamEvent } from './solStream'

vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))
vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

function messageEvent(content: string): SolStreamEvent {
  return { type: 'message', role: 'assistant', content, citations: [] }
}

const turn = (
  id: string,
  role: 'user' | 'assistant',
  attrs: Record<string, unknown>
): solApi.SolTurn => ({
  id,
  conversation_id: 'c1',
  role,
  content: role === 'user' ? 'where is the IMU' : 'The IMU is at 0x4A.',
  attrs,
  created_at: ''
})

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolSessionStore.getState().setConversation('p1', 'c1')
})

describe('answer source, budget ceiling and tool args on a turn (SOLUSDEV-321 P1-T6)', () => {
  it('keeps the answer source and the budget ceiling on the assistant item that streamed them', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'answer_source', answer: { source: 'graph', sources: ['config'] } })
      onEvent({ type: 'budget_reached', budget: { limit: 'tool_calls', used: 24, cap: 24 } })
      onEvent(messageEvent('The IMU is at 0x4A.'))
    })
    await act(async () => {
      await sendMessage('p1', 'where is the IMU', 'guide')
    })
    const [user, assistant] = selectSession(useSolChatStore.getState(), 'p1').items
    expect(user).not.toHaveProperty('answerSource')
    expect(user).not.toHaveProperty('budgetReached')
    expect(assistant.answerSource).toEqual({ source: 'graph', sources: ['config'] })
    expect(assistant.budgetReached).toEqual({ limit: 'tool_calls', used: 24, cap: 24 })
    expect(assistant).toMatchObject({ content: 'The IMU is at 0x4A.', pending: false })
  })

  it('hangs the redacted args of a call on its own trace step', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'tool_call',
        callId: 'k1',
        tool: 'get_entity',
        args: { entity_id: 'imu', password: '[REDACTED]' }
      })
      onEvent({ type: 'tool_result', callId: 'k1', ok: true, errorCode: null })
      onEvent({ type: 'tool_call', callId: 'k2', tool: 'list_findings' })
      onEvent(messageEvent('Done.'))
    })
    await act(async () => {
      await sendMessage('p1', 'check it', 'guide')
    })
    const assistant = selectSession(useSolChatStore.getState(), 'p1').items[1]
    expect(assistant.trace).toEqual([
      {
        callId: 'k1',
        tool: 'get_entity',
        ok: true,
        errorCode: null,
        args: { entity_id: 'imu', password: '[REDACTED]' }
      },
      { callId: 'k2', tool: 'list_findings', ok: null, errorCode: null }
    ])
  })

  it('a reloaded turn shows the same answer source and ceiling, read from its stored attrs', async () => {
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      turn('t2', 'assistant', {
        answer_source: 'graph',
        sources: ['config'],
        citations: ['[config:imu]'],
        budget_reached: { limit: 'web_searches', used: 1, cap: 1 }
      }),
      turn('t1', 'user', {})
    ])
    await act(async () => {
      await syncSession('p1')
    })
    const [user, assistant] = selectSession(useSolChatStore.getState(), 'p1').items
    expect(user).not.toHaveProperty('answerSource')
    expect(assistant.answerSource).toEqual({ source: 'graph', sources: ['config'] })
    expect(assistant.budgetReached).toEqual({ limit: 'web_searches', used: 1, cap: 1 })
  })
})

describe('a proposal’s reasoning on its turn (SOLUSDEV-321 P7)', () => {
  it('hangs a round’s reasoning frame on the proposal card it precedes', async () => {
    const reasoning = {
      considered: ['raise the lid 2 mm'],
      ruledOut: [{ what: 'a thinner wall', why: 'under the print minimum' }],
      proposing: 'Set WIDTH to 120 mm.'
    }
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'token', text: 'Checking the casing.' })
      onEvent({ type: 'reasoning', reasoning })
      onEvent({ type: 'tool_call', callId: 'k1', tool: 'onshape.set_variable' })
      onEvent({ type: 'tool_result', callId: 'k1', ok: true, errorCode: null })
      onEvent({
        type: 'tool_confirmation',
        pending: {
          confirmationId: 'cf1',
          tool: 'onshape.set_variable',
          summary: 'Set WIDTH to 120 mm',
          preview: []
        }
      })
      onEvent(messageEvent('It waits for your approval.'))
    })
    await act(async () => {
      await sendMessage('p1', 'make the port clear the casing', 'do')
    })
    const [user, assistant] = selectSession(useSolChatStore.getState(), 'p1').items
    expect(user).not.toHaveProperty('reasoning')
    expect(assistant.reasoning).toEqual([{ confirmationId: 'cf1', reasoning }])
    expect(assistant.confirmations.map((c) => c.confirmationId)).toEqual(['cf1'])
    expect(assistant.content).toBe('It waits for your approval.')
  })

  it('a reloaded turn carries no reasoning: the frame is shown live and never stored', async () => {
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      turn('t2', 'assistant', {}),
      turn('t1', 'user', {})
    ])
    await act(async () => {
      await syncSession('p1')
    })
    const [, assistant] = selectSession(useSolChatStore.getState(), 'p1').items
    expect(assistant).not.toHaveProperty('reasoning')
  })
})
