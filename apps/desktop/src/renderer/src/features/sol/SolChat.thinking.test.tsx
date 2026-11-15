// SOLUSDEV-326: SOL's thinking streams into the reply as it works, sits above the answer, and is
// still there after a reload (attrs.thinking).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import * as solApi from './solApi'
import { resetSolChatSessions } from './solChatStore'
import { SolChat } from './SolChat'
import { useSolSessionStore } from './solSessionStore'

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

/** True when `later` comes after `earlier` in the document. */
const follows = (earlier: Element, later: Element): boolean =>
  Boolean(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSettingsStore.setState({ solMode: 'Expert' })
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(resources.classifyQuery).mockReturnValue(new Promise(() => undefined))
})

describe('SolChat — SOL’s thinking (SOLUSDEV-326)', () => {
  it('streams the thought and the steps above the answer, then folds them', async () => {
    vi.mocked(solApi.streamSolMessage).mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'thinking', text: 'Check the IMU address first.' })
      onEvent({ type: 'tool_call', callId: 't1', tool: 'graph.get_entity' })
      onEvent({ type: 'tool_result', callId: 't1', ok: true, errorCode: null })
      onEvent({ type: 'thinking', text: 'It clashes with the baro.' })
      onEvent({ type: 'token', text: 'Both sit at 0x76.' })
      onEvent({ type: 'message', role: 'assistant', content: 'Both sit at 0x76.', citations: [] })
      onEvent({ type: 'done', conversationId: 'c1', turnId: 'a1' })
    })
    render(<SolChat projectId="p1" />)
    fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
      target: { value: 'Why is the IMU silent?' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    const toggle = await screen.findByRole('button', { name: /Thought for .* · 1 step/ })
    expect(follows(toggle, screen.getByText('Both sit at 0x76.'))).toBe(true)
    expect(screen.queryByTestId('tool-trace')).toBeNull()
  })

  it('shows a reloaded turn’s stored thought', async () => {
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      {
        id: 'a1',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'Both sit at 0x76.',
        attrs: { thinking: { segments: ['Check the IMU address first.'], ms: 3_000 } },
        created_at: '2026-11-14T00:00:00Z'
      }
    ])
    useSolSessionStore.setState({ conversationByProject: { p1: 'c1' } })
    render(<SolChat projectId="p1" />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Thought for 3s' })).toBeInTheDocument()
    )
  })
})
