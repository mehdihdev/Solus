// SOLUSDEV-324: the pill footer is the wireflow's 30 px row (sol-window.md
// "Frame": region chip · sees-your-screen · Think harder · Confirm every change
// · hide). The pre-flight routing line (`sol-reasoner-1 · quick · general`)
// belongs to the page composer only — in the pill it popped in mid-typing and
// squeezed the row onto two lines.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import type { ClassifyPreview } from '../../lib/api/resources'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions } from './solChatStore'
import { SolChat } from './SolChat'
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
  decideSolConfirmation: vi.fn()
}))
vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))

const PREVIEW: ClassifyPreview = {
  complexity: 'trivial',
  type: 'general',
  reasoner: { name: 'sol-reasoner-1', effort: 'quick' },
  cost_tier: 'low',
  source: { complexity: 'estimator', type: 'estimator' },
  tokens_estimate: 12,
  viable: true,
  reason: null,
  escalated: false,
  options: { complexities: [], types: [] }
} as unknown as ClassifyPreview

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolWindowStore.setState({ state: null, region: null })
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(resources.classifyQuery).mockResolvedValue(PREVIEW)
})

const type = (placeholder: RegExp, text: string): void =>
  void fireEvent.change(screen.getByPlaceholderText(placeholder), { target: { value: text } })

describe('pill footer', () => {
  it('never shows the routing line while typing; the footer toggles stay', async () => {
    render(<SolChat projectId="p1" layout="pill" />)
    type(/Ask SOL, or tell it what to do/, 'whats on my screen right now')
    await waitFor(() => expect(resources.classifyQuery).toHaveBeenCalled(), { timeout: 2000 })
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByTestId('classify-indicator')).not.toBeInTheDocument()
    expect(screen.queryByText(/sol-reasoner-1/)).not.toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Think harder' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Confirm every change' })).toBeInTheDocument()
  })

  it('the page composer still shows it (the preview did resolve)', async () => {
    render(<SolChat projectId="p1" layout="page" />)
    type(/Ask about a signal|Ask SOL/, 'whats on my screen right now')
    expect(
      await screen.findByTestId('classify-indicator', {}, { timeout: 2000 })
    ).toHaveTextContent('sol-reasoner-1 · quick · general')
  })
})
