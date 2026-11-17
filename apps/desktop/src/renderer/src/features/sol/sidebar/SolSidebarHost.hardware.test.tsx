// SOLUSDEV-326 — the SOL sidebar on the Hardware screen. It is the page's only SOL column: its
// chat is the Hardware surface (every turn goes as Build with confirmation), cards stay in the
// page's slot, there is no process strip, and it always docks.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Card } from '@solus/shared-types'
import * as solApi from '../solApi'
import * as resources from '../../../lib/api/resources'
import type { PendingConfirmation } from '../../../lib/api/solStream'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { resetSolChatSessions } from '../solChatStore'
import { useSolSessionStore } from '../solSessionStore'
import { useFocusStore } from '../../workspace/focusStore'
import { emptySections } from '../../graph/useSolusConfig'
import { uninstallSolBridge } from '../solWindow.fixtures'
import { sidebarCopy } from './sidebarCopy'
import { SolSidebarHost } from './SolSidebarHost'
import { useSolSidebarStore } from './solSidebarStore'

vi.mock('../solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConversations: vi.fn().mockResolvedValue([]),
  fetchArtifactBlob: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/resources')>()),
  classifyQuery: vi.fn(() => new Promise(() => undefined)),
  getSolus: vi.fn(),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../../../lib/api/resources.commands', () => ({
  getConfirmationOutput: vi.fn().mockResolvedValue({
    chunks: [],
    cursor: 0,
    complete: true,
    truncated: false
  })
}))
vi.mock('../ProcessStrip', () => ({ ProcessStrip: () => <div data-testid="process-strip" /> }))
vi.mock('../../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))
vi.mock('./sidebarEvents', () => ({ reportSidebarToggled: vi.fn() }))

const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const listSolConfirmations = vi.mocked(solApi.listSolConfirmations)

type Screen = 'hardware' | 'workspace'

const QUESTION: Card = {
  kind: 'offer',
  title: 'What should the robot be called?',
  body: 'Three servos answered.',
  more: null,
  field: null,
  primary: 'Use this name',
  secondary: 'Skip',
  receipt: 'Named',
  resumes: false
}
const row = (id: string, tool: string, card?: Card): PendingConfirmation => ({
  confirmationId: id,
  tool,
  summary: `summary of ${tool}`,
  preview: [],
  ...(card ? { card } : {})
})

/** The sidebar, open on `name`, over a conversation whose open rows are `rows`. */
function host(name: Screen, ...rows: PendingConfirmation[]): HTMLElement {
  if (rows.length > 0) {
    useSolSessionStore.setState({ conversationByProject: { p1: 'c1' } } as never)
    listSolConfirmations.mockResolvedValue(rows)
  }
  render(<SolSidebarHost route={{ name }} navigate={vi.fn()} />)
  return screen.getByRole('complementary', { name: 'SOL sidebar' })
}

const turns = (): solApi.StreamSolMessageInput[] =>
  streamSolMessage.mock.calls.map(([input]) => input)
const sent = async (): Promise<solApi.StreamSolMessageInput> => {
  await waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
  return turns()[turns().length - 1]
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  uninstallSolBridge()
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: {} } as never)
  useSolSidebarStore.getState().reset()
  useSolSidebarStore.getState().setOpen(true)
  useFocusStore.getState().reset()
  listSolConfirmations.mockResolvedValue([])
  streamSolMessage.mockResolvedValue(undefined as never)
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(resources.getSolus).mockResolvedValue({ entity_id: 's1', sections: emptySections() })
  vi.mocked(resources.decideSolConfirmation).mockResolvedValue({
    ok: true,
    value: { exit_code: 0 }
  } as Awaited<ReturnType<typeof resources.decideSolConfirmation>>)
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover' }, linked: true })
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
})

describe.each<[Screen, true | undefined]>([
  ['hardware', true],
  ['workspace', undefined]
])('the sidebar’s turns on %s', (name, forced) => {
  const asTheSurfaceSends = (input: solApi.StreamSolMessageInput): void => {
    expect(input.actionMode).toBe('do')
    expect(input.forceConfirmation).toBe(forced)
  }

  it('a typed send', async () => {
    const box = within(host(name)).getByPlaceholderText(sidebarCopy(name, null).placeholder)
    fireEvent.change(box, { target: { value: 'I have three servos' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    const input = await sent()
    expect(input.content).toBe('I have three servos')
    asTheSurfaceSends(input)
  })

  it('a suggestion chip', async () => {
    const chip = sidebarCopy(name, null).suggestions[0]
    fireEvent.click(await within(host(name)).findByRole('button', { name: chip }))
    const input = await sent()
    expect(input.content).toBe(chip)
    asTheSurfaceSends(input)
  })

  it('a decision in the thread resumes SOL the same way', async () => {
    const sb = host(name, row('make', 'code.exec'))
    const card = await within(sb).findByLabelText('Action needs your approval')
    fireEvent.click(within(card).getByRole('button', { name: 'Run command' }))
    const input = await sent()
    expect(input.resumeConfirmationId).toBe('make')
    asTheSurfaceSends(input)
  })
})

describe('an answer', () => {
  it('on Workspace goes from the thread as Build, with no forced confirmation', async () => {
    const sb = host('workspace', row('q1', 'ask_user', QUESTION))
    fireEvent.click(await within(sb).findByRole('button', { name: 'Skip' }))
    const input = await sent()
    expect(input.answer).toEqual({ question_id: 'q1', choice: 1 })
    expect(input.actionMode).toBe('do')
    expect(input.forceConfirmation).toBeUndefined()
  })

  it('on Hardware is the page’s: the question is in its slot, never in the sidebar', async () => {
    const sb = host('hardware', row('q1', 'ask_user', QUESTION), row('k2', 'onshape.set_variable'))
    expect(await within(sb).findByLabelText('Action needs your approval')).toBeInTheDocument()
    expect(within(sb).queryByRole('button', { name: 'Skip' })).toBeNull()
    expect(within(sb).queryByText('What should the robot be called?')).toBeNull()
  })
})

describe('the sidebar on Hardware', () => {
  it('greets as the Hardware screen', async () => {
    const sb = host('hardware')
    expect(within(sb).getByText('HARDWARE')).toBeInTheDocument()
    expect(await within(sb).findByText(/SOL sees what is plugged into this computer/)).toBeVisible()
    expect(within(sb).getByPlaceholderText('Ask SOL, or tell it what you have')).toBeVisible()
  })

  it('shows no process strip — a wake would skip the forced confirmation', () => {
    expect(within(host('hardware')).queryByTestId('process-strip')).toBeNull()
  })

  it('keeps the process strip everywhere else', () => {
    expect(within(host('workspace')).getByTestId('process-strip')).toBeInTheDocument()
  })

  it('docks at a 1000px window, where Workspace overlays', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
    const { rerender } = render(<SolSidebarHost route={{ name: 'hardware' }} navigate={vi.fn()} />)
    const panel = (): HTMLElement => screen.getByRole('complementary', { name: 'SOL sidebar' })
    expect(panel()).toHaveAttribute('data-fit', 'dock')
    rerender(<SolSidebarHost route={{ name: 'workspace' }} navigate={vi.fn()} />)
    expect(panel()).toHaveAttribute('data-fit', 'overlay')
    act(() => void window.dispatchEvent(new Event('resize')))
    rerender(<SolSidebarHost route={{ name: 'hardware' }} navigate={vi.fn()} />)
    expect(panel()).toHaveAttribute('data-fit', 'dock')
  })
})
