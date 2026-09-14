// SOL screen (SOLUSDEV-233 redesign): three columns — chats sidebar, the chat
// surface, and the context/usage panel. Still no fabricated robot data: the
// SOLUSDEV-152 pin evolves here — "GROUNDED IN N CONNECTIONS" is now allowed
// ONLY when driven by the project's real connected-source count from the
// server; without server truth the line must not render at all.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import { SolScreen } from './SolScreen'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolSessionStore } from './solSessionStore'
import { fakeSolBridge, installSolBridge, uninstallSolBridge } from './solWindow.fixtures'
import { disconnectSolBridge, useSolWindowStore } from './solWindowStore'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConversations: vi.fn().mockResolvedValue([]),
  deleteSolConversation: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  // Spread the real module: ArtifactCard (via SolChat) reads SOLUS_SECTIONS at load.
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn(),
  getProject: vi.fn(),
  updateSolMode: vi.fn().mockResolvedValue({}),
  getSettings: vi.fn(),
  updateCustomInstruction: vi.fn(),
  getUsage: vi.fn()
}))
vi.mock('../billing/useBillingData', () => ({
  useBillingData: vi.fn(() => ({
    status: 'ready',
    subscription: null,
    credits: null,
    packs: [],
    busy: false,
    notice: null,
    clearNotice: vi.fn(),
    startCheckout: vi.fn(),
    buyPack: vi.fn(),
    openPortal: vi.fn(),
    refresh: vi.fn()
  }))
}))
const listSolTurns = vi.mocked(solApi.listSolTurns)
const listSolConversations = vi.mocked(solApi.listSolConversations)
const getProject = vi.mocked(resources.getProject)
const getSettings = vi.mocked(resources.getSettings)
const getUsage = vi.mocked(resources.getUsage)
const updateSolMode = vi.mocked(resources.updateSolMode)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  listSolTurns.mockResolvedValue([])
  listSolConversations.mockResolvedValue([])
  getProject.mockRejectedValue(new Error('offline'))
  getSettings.mockResolvedValue({
    sol_mode: 'guide',
    sol_custom_instruction: null,
    data_collection_consent: false,
    onboarding_step: 'done'
  })
  getUsage.mockResolvedValue({
    used: 941,
    allowance: 10000,
    balance: 9059,
    cycle_start: '',
    cycle_end: ''
  })
  updateSolMode.mockResolvedValue({})
  useSettingsStore.setState({ solMode: 'Guide' })
  useWorkspaceStore.setState({
    teamId: 't1',
    project: { id: 'p1', name: 'Rover MK2' },
    linked: true
  })
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  disconnectSolBridge()
  useSolWindowStore.setState({ state: null, region: null })
  uninstallSolBridge()
})

describe('SolScreen — live chat surface', () => {
  it('keeps the SOL identity and scopes to the open project', () => {
    render(<SolScreen />)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText(/Rover MK2/)).toBeInTheDocument()
  })

  it('renders the chat input — the backend is wired (replaces the SOLUSDEV-152 pin)', () => {
    render(<SolScreen />)
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('loads the project conversation history', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([
      {
        id: 't1',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'The IMU shares the I2C bus.',
        attrs: {},
        created_at: ''
      }
    ])
    render(<SolScreen />)
    expect(await screen.findByText('The IMU shares the I2C bus.')).toBeInTheDocument()
    expect(listSolTurns).toHaveBeenCalledWith('p1', 'c1')
  })

  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    render(<SolScreen />)
    expect(screen.getByText(/Open a project to chat with SOL/)).toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })

  it('contains no scripted replies, fake grounding, or flash flow (SOLUSDEV-152 stands)', () => {
    // getProject rejects in this setup — with no server truth the grounded
    // line must not render at all (the 152 charter: real counts or nothing).
    const { container } = render(<SolScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES|GROUNDED IN/)
    expect(text).not.toMatch(/STM32H743|Apply & flash/)
    expect(text).not.toMatch(/τ_FL_knee|U4|DRV/)
    expect(text).not.toMatch(/strider/i)
  })

  it('grounds the header line in the project’s REAL source count', async () => {
    getProject.mockResolvedValue({
      id: 'p1',
      team_id: 't1',
      name: 'Rover MK2',
      description: null,
      archived_at: null,
      created_at: '',
      updated_at: '',
      stats: { entities: 0, relations: 0 },
      sources: [{ id: 's1' }, { id: 's2' }]
    } as unknown as resources.ProjectDetail)
    render(<SolScreen />)
    expect(await screen.findByText(/GROUNDED IN 2 CONNECTIONS/)).toBeInTheDocument()
  })
})

describe('SolScreen — SOLUSDEV-233 layout', () => {
  it('renders the chats sidebar and the context/usage panel', async () => {
    render(<SolScreen />)
    expect(screen.getByText('CHATS')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New chat' })).toBeInTheDocument()
    expect(screen.getByText('CONTEXT IN USE')).toBeInTheDocument()
    expect(screen.getByText('SOL USAGE')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('941 / 10,000')).toBeInTheDocument())
  })

  it('switches to a chat picked from the sidebar', async () => {
    listSolConversations.mockResolvedValue([
      {
        id: 'c2',
        project_id: 'p1',
        title: 'Diagnose run 41',
        created_by: 'u1',
        created_at: '2026-08-29T00:00:00Z',
        updated_at: '2026-08-29T00:00:00Z'
      }
    ])
    render(<SolScreen />)
    fireEvent.click(await screen.findByText('Diagnose run 41'))
    await waitFor(() => expect(listSolTurns).toHaveBeenCalledWith('p1', 'c2'))
    expect(useSolSessionStore.getState().conversationByProject).toEqual({ p1: 'c2' })
  })
})

describe('SolScreen — the SOL window hand-off (SOLUSDEV-252 S3, wireflow §F)', () => {
  it('offers "Open SOL window" under Electron and opens it through the bridge', () => {
    const bridge = fakeSolBridge()
    installSolBridge(bridge)
    render(<SolScreen />)
    fireEvent.click(screen.getByRole('button', { name: 'Open SOL window' }))
    expect(bridge.open).toHaveBeenCalledTimes(1)
  })

  it('hides the button outside Electron, where there is no window to open', () => {
    render(<SolScreen />)
    expect(screen.queryByRole('button', { name: 'Open SOL window' })).not.toBeInTheDocument()
  })
})
