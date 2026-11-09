// SOLUSDEV-321 P7 fix 1 (M1): a proposal's reasoning is mounted once PER CARD, so each block sits
// directly above its own card and goes with it when the card is decided. Split from
// SolChat.test.tsx, which is over its line cap.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import * as solApi from './solApi'
import { resetSolChatSessions } from './solChatStore'
import { SolChat } from './SolChat'
import { useSolSessionStore } from './solSessionStore'
import type { SolStreamEvent } from './solStream'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const card = (confirmationId: string, summary: string): SolStreamEvent => ({
  type: 'tool_confirmation',
  pending: { confirmationId, tool: 'onshape.set_variable', summary, preview: [] }
})

const reasoned = (proposing: string): SolStreamEvent => ({
  type: 'reasoning',
  reasoning: { considered: [], ruledOut: [], proposing }
})

/** True when `later` comes after `earlier` in the document. */
const follows = (earlier: Element, later: Element): boolean =>
  Boolean(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(resources.classifyQuery).mockReturnValue(new Promise(() => undefined))
})

describe('SolChat — a proposal’s reasoning sits on its own card (SOLUSDEV-321 P7)', () => {
  it('puts each card’s reasoning directly above that card, and takes it away with the card', async () => {
    vi.mocked(solApi.streamSolMessage).mockImplementation(async ({ onEvent }) => {
      onEvent(reasoned('Widen the lid.'))
      onEvent(card('cf1', 'Set WIDTH to 120 mm'))
      onEvent(reasoned('Move the port.'))
      onEvent(card('cf2', 'Set PORT_X to 40 mm'))
      onEvent({ type: 'message', role: 'assistant', content: 'Two changes wait.', citations: [] })
    })
    render(<SolChat projectId="p1" />)
    fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
      target: { value: 'make the port clear the lid' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getAllByTestId('reasoning-block')).toHaveLength(2))

    const [first, second] = screen.getAllByTestId('reasoning-block')
    const [cardOne, cardTwo] = screen.getAllByLabelText('Action needs your approval')
    expect(within(first).getByText('Widen the lid.')).toBeInTheDocument()
    expect(within(second).getByText('Move the port.')).toBeInTheDocument()
    expect(follows(first, cardOne) && follows(cardOne, second) && follows(second, cardTwo)).toBe(
      true
    )

    vi.mocked(resources.decideSolConfirmation).mockResolvedValue({ ok: true } as Awaited<
      ReturnType<typeof resources.decideSolConfirmation>
    >)
    await act(async () => {
      fireEvent.click(within(cardOne).getByRole('button', { name: 'Approve' }))
    })
    await waitFor(() => expect(screen.getAllByTestId('reasoning-block')).toHaveLength(1))
    expect(screen.queryByText('Widen the lid.')).not.toBeInTheDocument()
    expect(screen.getByText('Move the port.')).toBeInTheDocument()
  })
})
