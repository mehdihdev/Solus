// SOLUSDEV-317 §11.3: the store records which conversation started a process
// and runs wake turns through the same streaming path as a resume.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import { decideSolConfirmation } from '../../lib/api/resources'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { processOwner } from './processOwners'
import { streamSolMessage } from './solApi'
import {
  decideConfirmation,
  resetSolChatSessions,
  selectSession,
  useSolChatStore,
  wakeTurn,
  type ChatItem
} from './solChatStore'
import { useSolSessionStore } from './solSessionStore'

vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../../lib/api/resources.commands', () => ({ getConfirmationOutput: vi.fn() }))
vi.mock('./solApi', () => ({
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const decide = vi.mocked(decideSolConfirmation)
const stream = vi.mocked(streamSolMessage)

const START: PendingConfirmation = {
  confirmationId: 'cs',
  tool: 'code.process_start',
  summary: 'Start calibrate',
  preview: [{ label: 'program', before: null, after: './calibrate.sh' }]
}
const PROMPT = { processId: 'pr-1', promptSeq: 2 }

function seed(
  over: Partial<ReturnType<typeof session>> = {},
  ...cards: PendingConfirmation[]
): void {
  const item: ChatItem = {
    id: 'local-a',
    role: 'assistant',
    content: 'Starting it.',
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmations: cards,
    artifacts: []
  }
  useSolChatStore.setState({
    sessions: {
      p: {
        conversationId: 'c',
        items: [item],
        contextUsed: null,
        creditsExhausted: false,
        streaming: false,
        status: 'ready',
        ...over
      }
    }
  })
}

const session = (): ReturnType<typeof selectSession> =>
  selectSession(useSolChatStore.getState(), 'p')
const items = (): readonly ChatItem[] => session().items
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  vi.clearAllMocks()
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: { p: 'c' }, streaming: false })
  stream.mockResolvedValue(undefined)
})

describe('recording process owners', () => {
  it('records process_id → conversation from an approved code.process_start', async () => {
    decide.mockResolvedValue({ ok: true, value: { ok: true, process_id: 'pr-1', pid: 4 } })
    seed({}, START)
    await decideConfirmation('p', 'cs', 'approve')
    expect(processOwner('pr-1')).toEqual({ projectId: 'p', conversationId: 'c' })
  })

  it('records nothing when the result carries no process id', async () => {
    decide.mockResolvedValue({ ok: true, value: { ok: false, reason: 'limit' } })
    seed({}, START)
    await decideConfirmation('p', 'cs', 'approve')
    expect(processOwner('pr-1')).toBeNull()
  })

  it('forgets owners on an identity reset', async () => {
    decide.mockResolvedValue({ ok: true, value: { process_id: 'pr-1' } })
    seed({}, START)
    await decideConfirmation('p', 'cs', 'approve')
    resetSolChatSessions()
    expect(processOwner('pr-1')).toBeNull()
  })
})

describe('wakeTurn', () => {
  it('streams a wake turn with process_prompt and no user bubble', async () => {
    stream.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'message',
        role: 'assistant',
        content: 'It asks to continue.',
        citations: []
      })
    })
    seed()
    expect(wakeTurn('p', 'c', PROMPT, 'do')).toBe('started')
    await flush()
    expect(stream.mock.calls[0][0]).toMatchObject({
      projectId: 'p',
      conversationId: 'c',
      content: '',
      actionMode: 'do',
      processPrompt: PROMPT
    })
    expect(stream.mock.calls[0][0]).not.toHaveProperty('resumeConfirmationId')
    expect(items().map((m) => m.role)).toEqual(['assistant', 'assistant'])
    expect(items()[1].content).toBe('It asks to continue.')
  })

  it('carries the session’s confirm-every-change choice', async () => {
    seed({ forceConfirmation: true })
    wakeTurn('p', 'c', PROMPT, 'do')
    await flush()
    expect(stream.mock.calls[0][0]).toMatchObject({ forceConfirmation: true })
  })

  it('is busy while a turn streams, and starts nothing', () => {
    seed({ streaming: true })
    expect(wakeTurn('p', 'c', PROMPT, 'do')).toBe('busy')
    expect(stream).not.toHaveBeenCalled()
  })

  it('refuses a conversation that is not the open one', () => {
    seed()
    expect(wakeTurn('p', 'c-other', PROMPT, 'do')).toBe('elsewhere')
    expect(stream).not.toHaveBeenCalled()
  })

  it('silently drops an already_woken answer', async () => {
    stream.mockRejectedValue(new ApiError(409, 'already_woken', 'dup'))
    seed()
    wakeTurn('p', 'c', PROMPT, 'do')
    await flush()
    expect(items()).toHaveLength(1)
    expect(session().streaming).toBe(false)
  })

  it('shows "SOL paused" on resume_limit', async () => {
    stream.mockRejectedValue(new ApiError(409, 'resume_limit', 'limit'))
    seed()
    wakeTurn('p', 'c', PROMPT, 'guide')
    await flush()
    expect(items()[1]).toMatchObject({
      content: 'SOL paused — reply to continue',
      error: null,
      pending: false
    })
  })

  it('reports another failure like any failed turn', async () => {
    stream.mockRejectedValue(new ApiError(500, 'boom', 'boom'))
    seed()
    wakeTurn('p', 'c', PROMPT, 'do')
    await flush()
    expect(items()[1].error).toBe('SOL is unreachable right now.')
  })
})
