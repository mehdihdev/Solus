// SOLUSDEV-326 P3 follow-up: a call the gate parked is a step that waits, not one that failed.
// The gate answers a parked call `ok: false` / `unauthorized` — the code a real refusal uses too —
// and streams its `tool_confirmation` frame straight after (routers/sol.py `_drain_parked`). That
// frame is what tells the two apart live; after a reload it is the stored row's own words.
import { act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import * as solApi from './solApi'
import {
  cardDecided,
  decideConfirmation,
  resetSolChatSessions,
  selectSession,
  sendMessage,
  syncSession,
  useSolChatStore,
  type TraceEntry
} from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import type { SolStreamEvent } from './solStream'

vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))
vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof resources>()),
  decideSolConfirmation: vi.fn()
}))
const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const listSolTurns = vi.mocked(solApi.listSolTurns)
const decide = vi.mocked(resources.decideSolConfirmation)

const TOOL = 'hardware.inspect_device'
const call = (callId: string, tool = TOOL): SolStreamEvent => ({ type: 'tool_call', callId, tool })
const refused = (callId: string): SolStreamEvent => ({
  type: 'tool_result',
  callId,
  ok: false,
  errorCode: 'unauthorized'
})
const parkedFrame = (confirmationId: string, tool = TOOL): SolStreamEvent => ({
  type: 'tool_confirmation',
  pending: { confirmationId, tool, summary: 'Inspect the device', preview: [] }
})

async function streamed(...events: SolStreamEvent[]): Promise<void> {
  streamSolMessage.mockImplementation(async ({ onEvent }) => events.forEach(onEvent))
  await act(async () => void (await sendMessage('p1', 'what is this?', 'do')))
}
const steps = (): readonly TraceEntry[] =>
  selectSession(useSolChatStore.getState(), 'p1').items.flatMap((item) => item.trace)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolSessionStore.getState().setConversation('p1', 'c1')
  decide.mockResolvedValue({ ok: true, value: {} } as Awaited<ReturnType<typeof decide>>)
})

describe('a parked call, live', () => {
  it('is marked parked by the confirmation frame that follows its result', async () => {
    await streamed(call('k1'), refused('k1'), parkedFrame('conf-1'))
    expect(steps()).toMatchObject([{ callId: 'k1', parked: { confirmationId: 'conf-1' } }])
  })

  it('a refusal no card follows stays a refusal', async () => {
    // Guide refusing a gated call, or the same action proposed twice: no frame, no card.
    await streamed(call('k1'), refused('k1'), parkedFrame('conf-1'), call('k2'), refused('k2'))
    expect(steps()[0].parked).toEqual({ confirmationId: 'conf-1' })
    expect(steps()[1].parked).toBeUndefined()
  })

  it('only a refused step of the card’s own tool is taken for the parked one', async () => {
    await streamed(
      call('k1', 'graph.get_entity'),
      { type: 'tool_result', callId: 'k1', ok: true, errorCode: null },
      call('k2', 'code.exec'),
      refused('k2'),
      parkedFrame('conf-1')
    )
    expect(steps().map((step) => step.parked)).toEqual([undefined, undefined])
  })

  it('says what the person decided, in the thread and from the page’s slot', async () => {
    await streamed(
      call('k1'),
      refused('k1'),
      parkedFrame('conf-1'),
      call('k2', 'code.exec'),
      refused('k2'),
      parkedFrame('conf-2', 'code.exec')
    )
    await act(async () => void (await decideConfirmation('p1', 'conf-1', 'reject')))
    act(() => cardDecided('p1', 'conf-2', 'approve'))
    expect(steps().map((step) => step.parked)).toEqual([
      { confirmationId: 'conf-1', decision: 'reject' },
      { confirmationId: 'conf-2', decision: 'approve' }
    ])
  })
})

describe('a parked call, reloaded', () => {
  const toolRow = (id: string, words: string): solApi.SolTurn => ({
    id,
    conversation_id: 'c1',
    role: 'tool',
    content: `${TOOL} → ${words}`,
    attrs: {
      call: { call_id: `call-${id}`, tool: TOOL, args: {} },
      result: { call_id: `call-${id}`, ok: false, error: { code: 'unauthorized', message: 'x' } }
    },
    created_at: ''
  })
  const reply: solApi.SolTurn = {
    id: 'a1',
    conversation_id: 'c1',
    role: 'assistant',
    content: 'I have asked to inspect it.',
    attrs: {},
    created_at: ''
  }

  it('is a parked step when the stored row says so, and a refusal when it says the code', async () => {
    // The route returns newest first.
    listSolTurns.mockResolvedValue([
      reply,
      toolRow('t2', 'unauthorized'),
      toolRow('t1', 'parked, awaiting your approval')
    ])
    await act(async () => void (await syncSession('p1')))
    expect(steps().map((step) => step.parked)).toEqual([{}, undefined])
  })
})
