// SOLUSDEV-327: SOL decides for itself. No surface shows the Guide|Build mode, Think harder,
// Confirm every change or the routing line; every send goes in Build (`do`), auto-routed (no
// think-harder override, no pre-flight classify call) and without forcing confirmation — the
// server still cards destructive and unclassified actions (ADR action-mode amendment).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions } from './solChatStore'
import { SolChat } from './SolChat'
import { useSolWindowStore } from './solWindowStore'
import { SOL_STATE } from './solWindow.fixtures'

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

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  // The shared setting says Guide: the surfaces must still send Build.
  useSolWindowStore.setState({ state: { ...SOL_STATE, actionMode: 'guide' }, region: null })
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(solApi.streamSolMessage).mockResolvedValue(undefined)
})

const LAYOUTS = [
  ['page', /Ask SOL/],
  ['pill', /Ask SOL, or tell it what to do/],
  ['panel', /Ask about a signal/],
  ['sidebar', /Ask about a signal/]
] as const

describe.each(LAYOUTS)('%s composer', (layout, placeholder) => {
  it('shows no mode, Think harder, Confirm every change or routing line', async () => {
    render(<SolChat projectId="p1" layout={layout} />)
    fireEvent.change(screen.getByPlaceholderText(placeholder), { target: { value: 'whats this' } })
    await new Promise((r) => setTimeout(r, 450))
    expect(screen.queryByRole('switch', { name: 'Think harder' })).toBeNull()
    expect(screen.queryByRole('switch', { name: 'Confirm every change' })).toBeNull()
    expect(screen.queryByText(/auto routing/)).toBeNull()
    expect(screen.queryByTestId('classify-indicator')).toBeNull()
    expect(screen.queryByRole('radiogroup', { name: 'SOL action mode' })).toBeNull()
    expect(screen.queryByText('Build')).toBeNull()
    expect(screen.queryByText('Guide')).toBeNull()
    expect(resources.classifyQuery).not.toHaveBeenCalled()
  })

  it('sends in Build, auto-routed, without forcing confirmation', async () => {
    render(<SolChat projectId="p1" layout={layout} />)
    const box = screen.getByPlaceholderText(placeholder)
    fireEvent.change(box, { target: { value: 'wire the imu' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(solApi.streamSolMessage).toHaveBeenCalled())
    const input = vi.mocked(solApi.streamSolMessage).mock.calls[0][0]
    expect(input).toMatchObject({ content: 'wire the imu', actionMode: 'do' })
    expect(input.thinkHarder ?? false).toBe(false)
    expect(input.forceConfirmation ?? false).toBe(false)
  })
})
