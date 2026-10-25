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
import { emptySections } from '../graph/useSolusConfig'
import { chatKey, usePinnedContextStore } from './pinnedContextStore'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConversations: vi.fn().mockResolvedValue([]),
  deleteSolConversation: vi.fn(),
  renameSolConversation: vi.fn(),
  fetchArtifactBlob: vi.fn(),
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
  getUsage: vi.fn(),
  getSolus: vi.fn(),
  uploadArtifact: vi.fn(),
  addSolusEntry: vi.fn()
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
const getSolus = vi.mocked(resources.getSolus)
const uploadArtifact = vi.mocked(resources.uploadArtifact)
const addSolusEntry = vi.mocked(resources.addSolusEntry)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const onNavigate = vi.fn()
const page = (): React.JSX.Element => <SolScreen onNavigate={onNavigate} />

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
  getSolus.mockResolvedValue({ entity_id: 's1', sections: emptySections() })
  usePinnedContextStore.getState().resetForSignOut()
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
  it('heads the chat with its title and the honest pinned count', () => {
    render(page())
    expect(screen.getByText('0 NODES IN CONTEXT')).toBeInTheDocument()
    expect(screen.getAllByText('New chat').length).toBeGreaterThan(0) // header title (no chat yet)
  })

  it('renders the chat input — the backend is wired (replaces the SOLUSDEV-152 pin)', () => {
    render(page())
    expect(screen.getByPlaceholderText('Ask SOL about this project…')).toBeInTheDocument()
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
    render(page())
    expect(await screen.findByText('The IMU shares the I2C bus.')).toBeInTheDocument()
    expect(listSolTurns).toHaveBeenCalledWith('p1', 'c1')
  })

  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    render(page())
    expect(screen.getByText(/Open a project to chat with SOL/)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Ask SOL about this project…')).not.toBeInTheDocument()
  })

  it('contains no scripted replies, fake grounding, or flash flow (SOLUSDEV-152 stands)', () => {
    // getProject rejects in this setup — with no server truth the grounded
    // line must not render at all (the 152 charter: real counts or nothing).
    const { container } = render(page())
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES|GROUNDED IN/)
    expect(text).not.toMatch(/STM32H743|Apply & flash/)
    expect(text).not.toMatch(/τ_FL_knee|U4|DRV/)
    expect(text).not.toMatch(/strider/i)
  })
})

describe('SolScreen — SOLUSDEV-233 layout', () => {
  it('renders the chats sidebar, the context column and the usage card', async () => {
    render(page())
    expect(screen.getByRole('button', { name: 'New chat' })).toBeInTheDocument()
    expect(screen.getByText('CUSTOM INSTRUCTIONS')).toBeInTheDocument()
    expect(screen.getByText('FILES & IMAGES')).toBeInTheDocument()
    expect(screen.getByText('NODES IN CONTEXT')).toBeInTheDocument()
    expect(screen.getByText('ARTIFACTS')).toBeInTheDocument()
    expect(screen.getByText('CONTEXT IN USE')).toBeInTheDocument()
    expect(screen.getByText('SOL USAGE')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('941 / 10,000')).toBeInTheDocument())
  })

  it('counts the pinned nodes in the header, sends them as mentions, and unpins', async () => {
    usePinnedContextStore.getState().pin(chatKey('p1', null), {
      id: 'e1',
      name: 'IMU',
      domain: 'electrical',
      type: 'sensor'
    })
    usePinnedContextStore.getState().pin(chatKey('p1', null), {
      id: 'e2',
      name: 'Motor',
      domain: 'mechanical',
      type: 'actuator'
    })
    vi.mocked(solApi.createSolConversation).mockResolvedValue({
      id: 'c9',
      project_id: 'p1',
      title: 'hi',
      created_by: 'u1',
      created_at: '',
      updated_at: ''
    })
    streamSolMessage.mockImplementation(() => new Promise(() => undefined))
    render(page())
    expect(screen.getByText('2 NODES IN CONTEXT')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Message SOL'), { target: { value: 'hi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(
        expect.objectContaining({ mentions: ['e1', 'e2'] })
      )
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove Motor' }))
    expect(screen.getByText('1 NODE IN CONTEXT')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'From graph →' }))
    expect(onNavigate).toHaveBeenCalledWith('workspace')
  })

  it('the attach menu uploads into .solus documentation', async () => {
    uploadArtifact.mockResolvedValue({
      artifact_id: 'a1',
      uri: 'artifact://a1',
      media_type: 'image/png',
      storage: 's3',
      size_bytes: 3,
      summary: null
    })
    addSolusEntry.mockResolvedValue({} as resources.SolusEntry)
    render(page())
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Upload file or image' }))
    const file = new File(['x'], 'shot.png', { type: 'image/png' })
    const inputs = screen.getAllByLabelText('Upload file or image')
    fireEvent.change(inputs[0], { target: { files: [file] } })
    await waitFor(() => expect(uploadArtifact).toHaveBeenCalledWith('p1', file))
    await waitFor(() =>
      expect(addSolusEntry).toHaveBeenCalledWith(
        'p1',
        'documentation',
        expect.objectContaining({ kind: 'artifact', artifact_id: 'a1' })
      )
    )
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
    render(page())
    fireEvent.click(await screen.findByText('Diagnose run 41'))
    await waitFor(() => expect(listSolTurns).toHaveBeenCalledWith('p1', 'c2'))
    expect(useSolSessionStore.getState().conversationByProject).toEqual({ p1: 'c2' })
  })
})

describe('SolScreen — the SOL window hand-off (SOLUSDEV-252 S3, wireflow §F)', () => {
  it('offers "Open SOL window" under Electron and opens it through the bridge', () => {
    const bridge = fakeSolBridge()
    installSolBridge(bridge)
    render(page())
    fireEvent.click(screen.getByRole('button', { name: 'Open SOL window' }))
    expect(bridge.open).toHaveBeenCalledTimes(1)
  })

  it('hides the button outside Electron, where there is no window to open', () => {
    render(page())
    expect(screen.queryByRole('button', { name: 'Open SOL window' })).not.toBeInTheDocument()
  })
})
