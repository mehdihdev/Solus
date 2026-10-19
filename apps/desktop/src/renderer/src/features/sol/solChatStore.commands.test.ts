// SOLUSDEV-317: approving a command card keeps its output under the resulting
// message and continues SOL's turn (code-command-execution.md §5.5, sol-page.md
// "Command execution").
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import { ConfirmationRefused, decideSolConfirmation } from '../../lib/api/resources'
import { getConfirmationOutput } from '../../lib/api/resources.commands'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { streamSolMessage } from './solApi'
import {
  decideConfirmation,
  resetSolChatSessions,
  selectSession,
  useSolChatStore,
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
const output = vi.mocked(getConfirmationOutput)
const stream = vi.mocked(streamSolMessage)

const EXEC: PendingConfirmation = {
  confirmationId: 'cx',
  tool: 'code.exec',
  summary: 'Run colcon',
  preview: [{ label: 'program', before: null, after: '/opt/ros/jazzy/bin/colcon' }]
}
const ONSHAPE: PendingConfirmation = {
  confirmationId: 'co',
  tool: 'onshape.set_variable',
  summary: 'Set width',
  preview: []
}

function seed(...cards: PendingConfirmation[]): void {
  const item: ChatItem = {
    id: 'local-a',
    role: 'assistant',
    content: 'Let me build it.',
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
        status: 'ready'
      }
    }
  })
}

const items = (): readonly ChatItem[] => selectSession(useSolChatStore.getState(), 'p').items
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  vi.clearAllMocks()
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: { p: 'c' }, streaming: false })
  output.mockResolvedValue({
    chunks: [{ sequence: 1, stream: 'stdout', text: 'building <pkg>\n' }],
    cursor: 1,
    complete: true,
    truncated: false
  })
  stream.mockResolvedValue(undefined)
})

describe('retained command output', () => {
  it('keeps the final output and exit status under the message after the card goes', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 2 } })
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'approve')
    await flush()
    const [item] = items()
    expect(item.confirmations).toEqual([])
    expect(item.content).toMatch(/approval recorded/)
    expect(item.commandRuns).toEqual([
      expect.objectContaining({
        confirmationId: 'cx',
        text: 'building <pkg>\n',
        status: 'exited 2'
      })
    ])
  })

  it('shows the run while the approve request is still pending', async () => {
    let resolve!: (value: { ok: boolean; value: Record<string, unknown> }) => void
    decide.mockReturnValue(new Promise((r) => (resolve = r)))
    seed(EXEC)
    const deciding = decideConfirmation('p', 'cx', 'approve')
    await flush()
    expect(items()[0].commandRuns?.[0]).toMatchObject({ status: null, text: 'building <pkg>\n' })
    expect(items()[0].confirmations).toHaveLength(1)
    resolve({ ok: true, value: { exit_code: 0 } })
    await deciding
    expect(items()[0].commandRuns?.[0].status).toBe('exited 0')
  })

  it('marks a server refusal on the run and keeps the card', async () => {
    decide.mockRejectedValue(new ConfirmationRefused('sandbox unavailable: no probe'))
    seed(EXEC)
    await expect(decideConfirmation('p', 'cx', 'approve')).rejects.toThrow(/sandbox/)
    expect(items()[0].confirmations).toHaveLength(1)
    expect(items()[0].commandRuns?.[0].status).toBe('refused: sandbox unavailable: no probe')
  })

  it('drops the run on a transport failure, the card is still waiting', async () => {
    decide.mockRejectedValue(new Error('network'))
    seed(EXEC)
    await expect(decideConfirmation('p', 'cx', 'approve')).rejects.toThrow()
    expect(items()[0].commandRuns ?? []).toEqual([])
  })

  it('starts no output for a rejection', async () => {
    decide.mockResolvedValue({ ok: false })
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'reject')
    expect(output).not.toHaveBeenCalled()
    expect(items()[0].commandRuns ?? []).toEqual([])
  })
})

describe('automatic resume', () => {
  it('starts a resume turn with the confirmation id and no user bubble', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    stream.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'message', role: 'assistant', content: 'Build passed.', citations: [] })
    })
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'approve', { actionMode: 'do' })
    await flush()
    expect(stream).toHaveBeenCalledTimes(1)
    expect(stream.mock.calls[0][0]).toMatchObject({
      projectId: 'p',
      conversationId: 'c',
      resumeConfirmationId: 'cx',
      actionMode: 'do'
    })
    expect(items().map((m) => m.role)).toEqual(['assistant', 'assistant'])
    expect(items()[1].content).toBe('Build passed.')
  })

  it('carries the session’s confirm-every-change choice', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    seed(EXEC)
    useSolChatStore.setState((s) => ({
      sessions: { p: { ...s.sessions.p, forceConfirmation: true } }
    }))
    await decideConfirmation('p', 'cx', 'approve', { actionMode: 'do' })
    await flush()
    expect(stream.mock.calls[0][0]).toMatchObject({ forceConfirmation: true })
  })

  it('never resumes after a rejection or for a non-command card', async () => {
    decide.mockResolvedValue({ ok: false })
    seed(EXEC, ONSHAPE)
    await decideConfirmation('p', 'cx', 'reject', { actionMode: 'do' })
    decide.mockResolvedValue({ ok: true })
    await decideConfirmation('p', 'co', 'approve', { actionMode: 'do' })
    await flush()
    expect(stream).not.toHaveBeenCalled()
  })

  it('never resumes after a refused approval', async () => {
    decide.mockRejectedValue(new ConfirmationRefused('expired'))
    seed(EXEC)
    await expect(decideConfirmation('p', 'cx', 'approve', { actionMode: 'do' })).rejects.toThrow()
    await flush()
    expect(stream).not.toHaveBeenCalled()
  })

  it('shows "SOL paused" when the server answers resume_limit', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    stream.mockRejectedValue(new ApiError(409, 'resume_limit', 'limit'))
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'approve', { actionMode: 'guide' })
    await flush()
    expect(items()).toHaveLength(2)
    expect(items()[1]).toMatchObject({ content: 'SOL paused — reply to continue', error: null })
    expect(items()[1].pending).toBe(false)
  })

  it('silently drops an already_resumed answer', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    stream.mockRejectedValue(new ApiError(409, 'already_resumed', 'dup'))
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'approve', { actionMode: 'do' })
    await flush()
    expect(items()).toHaveLength(1)
    expect(selectSession(useSolChatStore.getState(), 'p').streaming).toBe(false)
  })

  it('reports another resume failure like any failed turn', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    stream.mockRejectedValue(new ApiError(500, 'boom', 'boom'))
    seed(EXEC)
    await decideConfirmation('p', 'cx', 'approve', { actionMode: 'do' })
    await flush()
    expect(items()[1].error).toBe('SOL is unreachable right now.')
  })
})
