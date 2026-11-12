// SOL screen (SOLUSDEV-233 redesign): three columns — chats sidebar, the chat
// surface, and the context/usage panel. Still no fabricated robot data: the
// SOLUSDEV-152 pin evolves here — "GROUNDED IN N CONNECTIONS" is now allowed
// ONLY when driven by the project's real connected-source count from the
// server; without server truth the line must not render at all.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import * as searchApi from '../../lib/api/search'
import { SolScreen } from './SolScreen'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions } from './solChatStore'
import { fakeSolBridge, installSolBridge, uninstallSolBridge } from './solWindow.fixtures'
import { disconnectSolBridge, useSolWindowStore } from './solWindowStore'
import { emptySections } from '../graph/useSolusConfig'
import { chatKey, usePinnedContextStore } from './pinnedContextStore'
import { useFocusStore } from '../workspace/focusStore'
import { useShellStore } from '../workspace/shellStore'
import { clearSearchCache } from '../workspace/useProjectSearch'

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
vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))
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
const searchProject = vi.mocked(searchApi.searchProject)
const onNavigate = vi.fn()
const page = (): React.JSX.Element => <SolScreen onNavigate={onNavigate} />
/** A canonical UUID from a hex tag: the server parses every anchor id as one, so the page drops
 *  any that is not (`pageAnchors`) — fixtures that are not UUIDs would never reach the wire. */
const uuid = (tag: string): string => `00000000-0000-4000-8000-${tag.padStart(12, '0')}`

beforeEach(() => {
  vi.clearAllMocks()
  clearSearchCache()
  useFocusStore.getState().reset()
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

  it('counts the pinned nodes in the header, sends them as pins, and unpins', async () => {
    usePinnedContextStore.getState().pin(chatKey('p1', null), {
      id: uuid('e1'),
      name: 'IMU',
      domain: 'electrical',
      type: 'sensor'
    })
    usePinnedContextStore.getState().pin(chatKey('p1', null), {
      id: uuid('e2'),
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
        expect.objectContaining({ pins: [uuid('e1'), uuid('e2')], mentions: [] })
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

/** A one-hit `GET /projects/{id}/search` answer — enough for the `@` picker. */
const oneHit = (id: string, name: string): searchApi.SearchResponse => ({
  entities: [
    { id, kind: 'part', domain: 'mechanical', name, snippet: '', score: 1, why: 'name_match' }
  ],
  solus: [],
  truncated: false
})

// SOLUSDEV-321 P0-T3: where the person is looking, what they @-pointed at and what they
// pinned are three different statements to SOL — three request fields, not one merged list.
describe('SolScreen — what a page send carries (SOLUSDEV-321 P0-T3)', () => {
  const pin = (id: string, name: string): void =>
    usePinnedContextStore
      .getState()
      .pin(chatKey('p1', null), { id, name, domain: 'electrical', type: 'sensor' })

  beforeEach(() => {
    // Each test leaves its turn streaming forever; sessions outlive components, so the next
    // test would be refused admission without this.
    resetSolChatSessions()
    vi.mocked(resources.classifyQuery).mockReturnValue(new Promise(() => undefined))
    vi.mocked(solApi.createSolConversation).mockResolvedValue({
      id: 'c9',
      project_id: 'p1',
      title: 'hi',
      created_by: 'u1',
      created_at: '',
      updated_at: ''
    })
    streamSolMessage.mockImplementation(() => new Promise(() => undefined))
  })

  it('page send carries focus, mentions and pins', async () => {
    pin(uuid('e1'), 'IMU')
    useFocusStore.setState({
      focusedEntityId: uuid('f1'),
      path: [
        {
          entity: { projectId: 'p1', entityId: uuid('f0') },
          domain: 'mechanical',
          relation: 'mounts'
        }
      ]
    })
    searchProject.mockResolvedValue(oneHit(uuid('c1'), 'Camera Bracket'))
    vi.useFakeTimers()
    try {
      render(page())
      fireEvent.change(screen.getByLabelText('Message SOL'), { target: { value: 'will @cam' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
      fireEvent.mouseDown(screen.getByRole('option', { name: /Camera Bracket/ }))
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
    } finally {
      vi.useRealTimers()
    }
    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        focus: { entityId: uuid('f1'), path: [uuid('f0')] },
        mentions: [uuid('c1')],
        pins: [uuid('e1')]
      })
    )
  })

  it('sends neither a focus nor pins when the person has neither', async () => {
    render(page())
    fireEvent.change(screen.getByLabelText('Message SOL'), { target: { value: 'hi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    const sent = streamSolMessage.mock.calls[0][0]
    expect(sent.mentions).toEqual([])
    expect(sent).not.toHaveProperty('focus')
    expect(sent).not.toHaveProperty('pins')
  })
})

// SOLUSDEV-321 P7: a citation the server verified that names a surface is a pill that opens it —
// a finding the Findings pane on the Live Bench, a .solus entry its node in the Workspace (whose
// sidebar shows the entry), an entity its node. Every other token stays a plain chip, and pills
// come from the structured `citations` alone, never from prose (SolChat.test.tsx pins that).
describe('SolScreen — citation pills (SOLUSDEV-321 P7)', () => {
  it('finding and solus pills open their surfaces', async () => {
    // Sessions outlive components: an earlier test's turn that never settles holds the project.
    resetSolChatSessions()
    const sections = emptySections()
    sections.documentation = [
      {
        id: 'd1',
        section: 'documentation',
        subsection: null,
        kind: 'text',
        author: 'user',
        text: 'The wiring notes',
        name: null,
        artifact_id: null,
        entity_id: uuid('n1'),
        media_type: null,
        size_bytes: null,
        created_by: null,
        created_at: '',
        updated_at: ''
      }
    ]
    getSolus.mockResolvedValue({ entity_id: 's1', sections })
    vi.mocked(solApi.createSolConversation).mockResolvedValue({
      id: 'c9',
      project_id: 'p1',
      title: 'why is it hot',
      created_by: 'u1',
      created_at: '',
      updated_at: ''
    })
    const part = uuid('e7')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'message',
        role: 'assistant',
        content: 'It runs hot, past the wiring notes.',
        citations: ['[finding:f1]', '[solus:documentation:d1]', `[entity:${part}]`, '[kicad:U4]']
      })
    })
    render(page())
    await waitFor(() => expect(getSolus).toHaveBeenCalledWith('p1'))
    fireEvent.change(screen.getByLabelText('Message SOL'), { target: { value: 'why is it hot' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    const region = await screen.findByTestId('citations-region')
    expect(within(region).getAllByRole('button')).toHaveLength(3)
    expect(within(region).getByText('[kicad:U4]').closest('button')).toBeNull()

    // The Bench opens ON the cited finding: the shell carries it there (BenchScreen.test.tsx).
    useShellStore.getState().reset()
    fireEvent.click(within(region).getByText('[finding:f1]'))
    expect(useShellStore.getState().benchFinding).toBe('f1')
    expect(onNavigate).toHaveBeenLastCalledWith('bench')

    fireEvent.click(within(region).getByText('[solus:documentation:d1]'))
    expect(useFocusStore.getState().focusedEntityId).toBe(uuid('n1'))
    expect(onNavigate).toHaveBeenLastCalledWith('workspace')

    fireEvent.click(within(region).getByText(`[entity:${part}]`))
    expect(useFocusStore.getState().focusedEntityId).toBe(part)
    expect(onNavigate).toHaveBeenCalledTimes(3)
  })

  it('the usage panel + opens the Billing screen (SOLUSDEV-325)', async () => {
    render(page())
    fireEvent.click(await screen.findByRole('button', { name: 'Add credits' }))
    expect(onNavigate).toHaveBeenCalledWith('billing')
    expect(useShellStore.getState().billingFocus).toBe('credits')
  })
})
