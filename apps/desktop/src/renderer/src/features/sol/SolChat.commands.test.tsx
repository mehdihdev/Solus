// SOLUSDEV-317 on the chat surface: Cmd/Ctrl+Enter approves the newest pending
// command card, the output stays under the message, and SOL resumes.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import * as commands from '../../lib/api/resources.commands'
import type { PendingConfirmation } from '../../lib/api/solStream'
import * as solApi from './solApi'
import { SolChat } from './SolChat'
import { ARM_DELAY_MS } from './commandHotkey'
import { PreviewObserverContext, type ObserveInView } from './previewInView'
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
  vi.restoreAllMocks()
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

/** The jsdom seam for IntersectionObserver: by default every preview reports
 *  itself in view the moment it is observed; a test can take over a card. */
let observe: ObserveInView
const inView = new Map<string, (visible: boolean) => void>()
const previewsInViewAtOnce: ObserveInView = (_element, onChange) => {
  onChange(true)
  return () => undefined
}

beforeEach(() => {
  inView.clear()
  observe = previewsInViewAtOnce
})

/** Move the clock past the shortcut's arming delay (cards must have been on
 *  screen, newest, for ARM_DELAY_MS). */
function armCards(): void {
  const now = Date.now()
  vi.spyOn(Date, 'now').mockReturnValue(now + ARM_DELAY_MS)
}

/** Send one message whose turn parks the given cards. */
async function park(
  user: ReturnType<typeof userEvent.setup>,
  ...cards: PendingConfirmation[]
): Promise<HTMLElement> {
  stream.mockImplementationOnce(async ({ onEvent }) => {
    for (const pending of cards) onEvent({ type: 'tool_confirmation', pending })
  })
  render(
    <PreviewObserverContext.Provider value={observe}>
      <SolChat projectId="p1" />
    </PreviewObserverContext.Provider>
  )
  const input = screen.getByPlaceholderText('Ask about a signal, a change, a part…')
  await user.type(input, 'build it{Enter}')
  await screen.findAllByLabelText('Action needs your approval')
  stream.mockResolvedValue(undefined)
  return input
}

describe('Cmd/Ctrl+Enter approval', () => {
  it('approves the newest pending command card from an empty composer', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = userEvent.setup()
    const input = await park(user, command('older'), command('newer'), ONSHAPE)
    input.focus()
    armCards()
    await user.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve'))
    expect(decide).toHaveBeenCalledTimes(1)
    // The key approved; it never sent a message (only the resume may follow).
    expect(stream.mock.calls.filter(([arg]) => !arg.resumeConfirmationId)).toHaveLength(1)
  })
})

describe('Cmd/Ctrl+Enter: composer drafts and preview visibility', () => {
  it('never approves while the composer holds a draft, and does not send it', async () => {
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    await user.type(input, 'no, do not run that')
    armCards()
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
    expect(input).toHaveValue('no, do not run that')
    expect(stream).toHaveBeenCalledTimes(1)
  })

  it('approves from outside the composer even when the composer holds a draft', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    await user.type(input, 'draft')
    armCards()
    const approve = screen.getByRole('button', { name: /Approve/ })
    act(() => {
      fireEvent.keyDown(approve, { key: 'Enter', ctrlKey: true })
    })
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve'))
  })

  it('does not approve a card whose preview never came into view', async () => {
    observe = () => () => undefined
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    input.focus()
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 100 * ARM_DELAY_MS)
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
    expect(stream).toHaveBeenCalledTimes(1)
  })

  it('restarts the clock when the preview leaves view before arming', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    observe = (_element, onChange) => {
      inView.set('newer', onChange)
      return () => undefined
    }
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    input.focus()
    const t0 = Date.now() + 10 * ARM_DELAY_MS
    const clock = vi.spyOn(Date, 'now').mockReturnValue(t0)
    act(() => inView.get('newer')?.(true))
    clock.mockReturnValue(t0 + ARM_DELAY_MS - 100)
    act(() => inView.get('newer')?.(false))
    clock.mockReturnValue(t0 + ARM_DELAY_MS)
    act(() => inView.get('newer')?.(true))
    clock.mockReturnValue(t0 + 2 * ARM_DELAY_MS - 1)
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
    clock.mockReturnValue(t0 + 2 * ARM_DELAY_MS)
    await user.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve'))
  })
})

describe('Cmd/Ctrl+Enter guards', () => {
  it('ignores the shortcut while the newest command card is busy', async () => {
    decide.mockReturnValue(new Promise(() => undefined))
    const user = userEvent.setup()
    const input = await park(user, command('older'), command('newer'))
    input.focus()
    armCards()
    await user.keyboard('{Control>}{Enter}{/Control}')
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).toHaveBeenCalledTimes(1)
    expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve')
  })

  it('does nothing — and sends nothing — before the newest card is armed', async () => {
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    input.focus()
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
    expect(stream).toHaveBeenCalledTimes(1)
  })

  it('ignores auto-repeat and needs a keyup between shortcut approvals', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = userEvent.setup()
    const input = await park(user, command('older'), command('newer'))
    armCards()
    act(() => {
      fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true, repeat: true })
    })
    expect(decide).not.toHaveBeenCalled()
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
    })
    expect(decide).toHaveBeenCalledWith('p1', 'newer', 'approve')
    await waitFor(() =>
      expect(screen.getAllByLabelText('Action needs your approval')).toHaveLength(1)
    )
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 10 * ARM_DELAY_MS)
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
    })
    expect(decide).toHaveBeenCalledTimes(1)
    await act(async () => {
      fireEvent.keyUp(input, { key: 'Enter' })
      fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
    })
    expect(decide).toHaveBeenCalledTimes(2)
    expect(decide).toHaveBeenLastCalledWith('p1', 'older', 'approve')
  })
})

describe('Cmd/Ctrl+Enter: keys that never approve', () => {
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
    armCards()
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(decide).not.toHaveBeenCalled()
  })

  it('ignores Cmd+Enter off macOS', async () => {
    const user = userEvent.setup()
    const input = await park(user, command('newer'))
    input.focus()
    armCards()
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    expect(decide).not.toHaveBeenCalled()
  })
})

describe('after an approved command', () => {
  it('keeps the output and exit status under the message and resumes SOL', async () => {
    decide.mockResolvedValue({ ok: true, value: { ok: false, exit_code: 2, reason: null } })
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
