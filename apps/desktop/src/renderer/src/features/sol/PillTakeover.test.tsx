// SOLUSDEV-319: a pending command card takes over the Ember Pill — the thread,
// strip and composer step aside (inert) while the card holds the whole pill, and
// come back once it is decided. Other surfaces and other cards never take over.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import * as commands from '../../lib/api/resources.commands'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { newestPendingCommand } from './PillTakeover'
import * as solApi from './solApi'
import { SolChat } from './SolChat'
import { PreviewObserverContext, type ObserveInView } from './previewInView'
import { resetSolChatSessions, type ChatItem } from './solChatStore'
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
  stopCodeProcess: vi.fn(),
  sendCodeProcessInput: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const stream = vi.mocked(solApi.streamSolMessage)
const decide = vi.mocked(resources.decideSolConfirmation)

const command = (confirmationId: string): PendingConfirmation => ({
  confirmationId,
  tool: 'code.exec',
  summary: `Run ${confirmationId}`,
  preview: [{ label: 'program', before: null, after: `/usr/bin/${confirmationId}` }]
})
const ONSHAPE: PendingConfirmation = {
  confirmationId: 'onshape',
  tool: 'onshape.set_variable',
  summary: 'Set width',
  preview: [{ label: 'width', before: '1', after: '2' }]
}
const PILL_PLACEHOLDER = 'Ask SOL, or tell it what to do…'
const PANEL_PLACEHOLDER = 'Ask about a signal, a change, a part…'

const inViewAtOnce: ObserveInView = (_element, onChange) => {
  onChange(true)
  return () => undefined
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
  vi.mocked(commands.getConfirmationOutput).mockResolvedValue({
    chunks: [],
    cursor: 0,
    complete: true,
    truncated: false
  })
})

async function park(
  layout: 'pill' | 'panel',
  ...cards: PendingConfirmation[]
): Promise<ReturnType<typeof userEvent.setup>> {
  const user = userEvent.setup()
  stream.mockImplementationOnce(async ({ onEvent }) => {
    for (const pending of cards) onEvent({ type: 'tool_confirmation', pending })
  })
  render(
    <PreviewObserverContext.Provider value={inViewAtOnce}>
      <SolChat projectId="p1" layout={layout} />
    </PreviewObserverContext.Provider>
  )
  const placeholder = layout === 'pill' ? PILL_PLACEHOLDER : PANEL_PLACEHOLDER
  await user.type(screen.getByPlaceholderText(placeholder), 'build it{Enter}')
  stream.mockResolvedValue(undefined)
  return user
}

const takeover = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('.sol-pill-takeover:not([data-leaving])')

describe('the Ember Pill command takeover', () => {
  it('holds the whole pill with the card and steps the rest aside', async () => {
    await park('pill', command('make'))
    const card = await screen.findByRole('region', { name: 'Action needs your approval' })
    expect(takeover()).toContainElement(card)
    expect(card).toHaveAttribute('data-variant', 'pill')
    // Exactly one card: the thread does not render a second copy.
    expect(screen.getAllByRole('region', { name: 'Action needs your approval' })).toHaveLength(1)
    // The composer is inert (out of the tab order and the accessibility tree).
    const composer = screen.getByPlaceholderText(PILL_PLACEHOLDER, { exact: true })
    expect(composer.closest('[inert]')).not.toBeNull()
    expect(document.querySelector('.sol-pill-stack')).toHaveAttribute('data-takeover', 'on')
  })

  it('moves focus to the card itself, never onto Run', async () => {
    await park('pill', command('make'))
    await screen.findByRole('region', { name: 'Action needs your approval' })
    await waitFor(() => expect(document.activeElement).toBe(takeover()))
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'Run' }))
  })

  it('gives the pill back once the command is decided', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = await park('pill', command('make'))
    await user.click(await screen.findByRole('button', { name: 'Run' }))
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'make', 'approve'))
    await waitFor(() =>
      expect(document.querySelector('.sol-pill-stack')).toHaveAttribute('data-takeover', 'off')
    )
    expect(screen.queryByRole('region', { name: 'Action needs your approval' })).toBeNull()
    const composer = screen.getByPlaceholderText(PILL_PLACEHOLDER)
    expect(composer.closest('[inert]')).toBeNull()
    // The card leaves as an inert, unlabelled ghost, then is gone.
    await waitFor(() => expect(document.querySelector('.sol-pill-takeover')).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(composer))
  })

  it('takes over with the newest command, then the next one', async () => {
    decide.mockResolvedValue({ ok: true, value: { exit_code: 0 } })
    const user = await park('pill', command('older'), command('newer'))
    const first = await screen.findByRole('region', { name: 'Action needs your approval' })
    expect(within(first).getByText('Run newer')).toBeInTheDocument()
    await user.click(within(first).getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(screen.getByText('Run older')).toBeInTheDocument())
    expect(takeover()).toContainElement(screen.getByText('Run older'))
  })

  it('does not take over for a non-command approval', async () => {
    await park('pill', ONSHAPE)
    await screen.findByText('Set width')
    expect(takeover()).toBeNull()
    expect(document.querySelector('.sol-pill-stack')).toHaveAttribute('data-takeover', 'off')
  })

  it('never takes over outside the pill', async () => {
    await park('panel', command('make'))
    const card = await screen.findByRole('region', { name: 'Action needs your approval' })
    expect(card).toHaveAttribute('data-variant', 'card')
    expect(takeover()).toBeNull()
  })
})

describe('newestPendingCommand', () => {
  const item = (id: string, confirmations: PendingConfirmation[]): ChatItem =>
    ({ id, role: 'assistant', content: '', confirmations }) as unknown as ChatItem

  it('is the last command card across the transcript', () => {
    const items = [item('a', [command('x')]), item('b', [command('y'), ONSHAPE])]
    expect(newestPendingCommand(items)?.confirmationId).toBe('y')
  })

  it('is null with no command card', () => {
    expect(newestPendingCommand([item('a', [ONSHAPE])])).toBeNull()
    expect(newestPendingCommand([])).toBeNull()
  })
})
