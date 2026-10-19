// SOLUSDEV-317 on the chat surface: Cmd/Ctrl+Enter approves the newest pending
// command card, the output stays under the message, and SOL resumes.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import * as commands from '../../lib/api/resources.commands'
import type { PendingConfirmation } from '../../lib/api/solStream'
import * as solApi from './solApi'
import { SolChat } from './SolChat'
import { resetSolChatSessions } from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { useSolWindowStore } from './solWindowStore'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn(),
  listEntities: vi.fn()
}))
vi.mock('../../lib/api/resources.commands', () => ({
  getConfirmationOutput: vi.fn(),
  listCodeProcesses: vi.fn(),
  getCodeProcessOutput: vi.fn(),
  stopCodeProcess: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const stream = vi.mocked(solApi.streamSolMessage)
const decide = vi.mocked(resources.decideSolConfirmation)
const output = vi.mocked(commands.getConfirmationOutput)

const command = (confirmationId: string, tool = 'code.exec'): PendingConfirmation => ({
  confirmationId,
  tool,
  summary: `Run ${confirmationId}`,
  preview: [{ label: 'program', before: null, after: `/usr/bin/${confirmationId}` }]
})
const ONSHAPE: PendingConfirmation = {
  confirmationId: 'onshape',
  tool: 'onshape.set_variable',
  summary: 'Set width',
  preview: []
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolWindowStore.setState({ state: null, region: null })
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(resources.classifyQuery).mockReturnValue(new Promise(() => undefined))
  output.mockResolvedValue({
    chunks: [{ sequence: 1, stream: 'stdout', text: 'compiled <ok>' }],
    cursor: 1,
    complete: true,
    truncated: false
  })
})

/** Send one message whose turn parks the given cards. */
async function park(
  user: ReturnType<typeof userEvent.setup>,
  ...cards: PendingConfirmation[]
): Promise<HTMLElement> {
  stream.mockImplementationOnce(async ({ onEvent }) => {
    for (const pending of cards) onEvent({ type: 'tool_confirmation', pending })
  })
  render(<SolChat projectId="p1" />)
  const input = screen.getByPlaceholderText('Ask about a signal, a change, a part…')
  await user.type(input, 'build it{Enter}')
  await screen.findAllByLabelText('Action needs your approval')
  stream.mockResolvedValue(undefined)
  return input
}

describe('Cmd/Ctrl+Enter approval', () => {
  it('approves the newest pending command card and does not submit the composer', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = userEvent.setup()
    const input = await park(user, command('older'), command('newer'), ONSHAPE)
    await user.type(input, 'draft')
    await user.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve'))
    expect(decide).toHaveBeenCalledTimes(1)
    // The composer kept its text: the key approved, it did not send.
    expect(input).toHaveValue('draft')
    expect(stream.mock.calls.filter(([arg]) => arg.content === 'draft')).toEqual([])
  })

  it('ignores the shortcut while the newest command card is busy', async () => {
    decide.mockReturnValue(new Promise(() => undefined))
    const user = userEvent.setup()
    const input = await park(user, command('older'), command('newer'))
    input.focus()
    await user.keyboard('{Control>}{Enter}{/Control}')
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).toHaveBeenCalledTimes(1)
    expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve')
  })

  it('ignores the shortcut during IME composition', async () => {
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    act(() => {
      input.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          ctrlKey: true,
          isComposing: true,
          bubbles: true
        })
      )
    })
    expect(decide).not.toHaveBeenCalled()
  })

  it('never approves a non-command card from the keyboard', async () => {
    const user = userEvent.setup()
    const input = await park(user, ONSHAPE)
    input.focus()
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
  })

  it('ignores Cmd+Enter off macOS', async () => {
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    input.focus()
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    expect(decide).not.toHaveBeenCalled()
  })
})

describe('after an approved command', () => {
  it('keeps the output and exit status under the message and resumes SOL', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 2 } })
    const user = userEvent.setup()
    await park(user, command('make'))
    const card = screen.getByLabelText('Action needs your approval')
    await user.click(within(card).getByRole('button', { name: 'Approve' }))
    await waitFor(() =>
      expect(screen.queryByLabelText('Action needs your approval')).not.toBeInTheDocument()
    )
    const region = await screen.findByLabelText('Command output')
    expect(within(region).getByText('compiled <ok>')).toBeInTheDocument()
    expect(within(region).getByText('exited 2')).toBeInTheDocument()
    await waitFor(() =>
      expect(stream).toHaveBeenCalledWith(
        expect.objectContaining({ resumeConfirmationId: 'make', actionMode: 'do' })
      )
    )
    // No user bubble for the resume: only the one message the person typed.
    expect(screen.getAllByText('build it')).toHaveLength(1)
  })

  it('does not resume after a rejection', async () => {
    decide.mockResolvedValue({ ok: false })
    const user = userEvent.setup()
    await park(user, command('make'))
    const card = screen.getByLabelText('Action needs your approval')
    await user.click(within(card).getByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(screen.queryByLabelText('Action needs your approval')).not.toBeInTheDocument()
    )
    expect(stream).toHaveBeenCalledTimes(1)
  })
})
