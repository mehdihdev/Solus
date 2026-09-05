// Per-project Sources page (SOLUSDEV-164): the missing add/remove/select
// integration surface. Lists connected sources with sync + disconnect actions,
// and a connect catalog reusing the onboarding tiles. Disconnect keeps synced
// graph data (the user's chosen semantics).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SourcesScreen } from './SourcesScreen'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import type { Source } from '../../lib/api/resources'
import * as sourcesHook from './useProjectSources'
import * as catalogHook from '../onboarding/useIntegrationCatalog'
import * as oauthHook from '../onboarding/useOAuthConnect'
import * as edaHook from '../onboarding/useEdaConnect'

vi.mock('./useProjectSources', () => ({ useProjectSources: vi.fn() }))
vi.mock('../onboarding/useIntegrationCatalog', () => ({ useIntegrationCatalog: vi.fn() }))
vi.mock('../onboarding/useOAuthConnect', () => ({ useOAuthConnect: vi.fn() }))
vi.mock('../onboarding/useEdaConnect', () => ({ useEdaConnect: vi.fn() }))
// Local Connections data hooks (SOLUSDEV-72): stubbed to their honest offline
// shapes so this screen's tests never touch the network.
vi.mock('./localconnections/useLocalConnections', () => ({
  useLocalConnections: vi.fn(() => ({ data: null, refresh: vi.fn() })),
  useLocalTools: vi.fn(() => null)
}))
vi.mock('../workspace/useBridgeStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../workspace/useBridgeStatus')>()
  return { ...actual, useBridgeStatus: vi.fn(() => null) }
})

const SOURCE = (over: Partial<Source> = {}): Source =>
  ({
    id: 's1',
    project_id: 'p1',
    type: 'github',
    name: 'octo/arm',
    status: 'connected',
    config: {},
    account_login: null,
    last_synced_at: null,
    last_error: null,
    entity_count: 8,
    created_at: '',
    updated_at: '',
    ...over
  }) as Source

const syncNow = vi.fn()
const disconnect = vi.fn()

function mockSources(sources: Source[], status: sourcesHook.ProjectSourcesStatus = 'ready'): void {
  vi.mocked(sourcesHook.useProjectSources).mockReturnValue({
    status,
    sources,
    actions: { refresh: vi.fn(), syncNow, disconnect }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useOnboardingStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
  syncNow.mockResolvedValue(true)
  disconnect.mockResolvedValue(true)
  vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([
    {
      id: 'github',
      name: 'GitHub',
      kind: 'Code',
      mark: 'GH',
      mode: 'oauth',
      configFields: ['repo', 'branch'],
      selection: { mode: 'single', config_key: 'repo', label: 'repository' },
      accessModes: null,
      hosted: null
    },
    {
      id: 'kicad',
      name: 'KiCad',
      kind: 'PCB',
      mark: 'Ki',
      mode: 'export-file',
      configFields: ['export'],
      selection: null,
      accessModes: null,
      hosted: null
    }
  ])
  vi.mocked(oauthHook.useOAuthConnect).mockReturnValue({
    start: vi.fn(async () => ({ ok: true })),
    startAccount: vi.fn(async () => ({ ok: true })),
    select: vi.fn(),
    submitConfig: vi.fn(),
    chooseAccess: vi.fn(),
    cancel: vi.fn()
  })
  vi.mocked(edaHook.useEdaConnect).mockReturnValue({
    start: vi.fn(async () => ({ ok: true })),
    cancel: vi.fn()
  })
})

describe('SourcesScreen', () => {
  it('shows which account a source is connected as', async () => {
    mockSources([SOURCE({ account_login: 'octocat' })])
    render(<SourcesScreen />)
    expect(await screen.findByText(/octocat/)).toBeInTheDocument()
  })

  it('shows no account rather than an invented one when the provider gives none', async () => {
    // Onshape's read-only scope carries no PII, so there may genuinely be no
    // human-readable login. A blank is honest; a placeholder name is not.
    mockSources([SOURCE({ account_login: null, name: 'Onshape' })])
    render(<SourcesScreen />)
    await screen.findByText('Onshape')
    expect(screen.queryByText(/onshape-user/)).not.toBeInTheDocument()
  })

  it('prompts to pick a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    mockSources([], 'offline')
    render(<SourcesScreen />)
    expect(screen.getByText(/select a project/i)).toBeInTheDocument()
  })

  it('lists connected sources with their status', () => {
    mockSources([SOURCE()])
    render(<SourcesScreen />)
    expect(screen.getByText('octo/arm')).toBeInTheDocument()
    expect(screen.getByText('CONNECTED')).toBeInTheDocument()
  })

  it('renders the message of a structured sync error without crashing (SOLUSDEV-114)', () => {
    // The real API serializes last_error as {code, message} (models.Source.last_error
    // is a JSON column) — rendering the raw object crashed the whole app.
    mockSources([
      SOURCE({
        status: 'error',
        // No cast: last_error is typed as the structured object, so reverting
        // the SOLUSDEV-114 type fix breaks this test at compile time too.
        last_error: {
          code: 'export_format_unsupported',
          message: 'kicad: the S-expression netlist is not supported in v1; re-export as XML.'
        }
      })
    ])
    render(<SourcesScreen />)
    expect(screen.getByText(/re-export as XML/i)).toBeInTheDocument()
  })

  it('syncs a source on demand', async () => {
    mockSources([SOURCE()])
    render(<SourcesScreen />)
    await userEvent.click(screen.getByRole('button', { name: /sync now/i }))
    expect(syncNow).toHaveBeenCalledWith('s1')
  })

  it('confirms before disconnecting and keeps synced data', async () => {
    mockSources([SOURCE()])
    render(<SourcesScreen />)
    await userEvent.click(screen.getByRole('button', { name: /disconnect octo\/arm/i }))
    // Confirmation must state that synced data is retained.
    expect(screen.getByText(/keeps/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^disconnect$/i }))
    await waitFor(() => expect(disconnect).toHaveBeenCalledWith('s1'))
  })

  it('renders the connect catalog for adding tools', () => {
    mockSources([])
    render(<SourcesScreen />)
    expect(screen.getByText('GitHub')).toBeInTheDocument()
    expect(screen.getByText('KiCad')).toBeInTheDocument()
  })

  it('shows an honest offline note instead of a source list', () => {
    mockSources([], 'offline')
    render(<SourcesScreen />)
    expect(screen.getAllByText(/can't reach its API/i).length).toBeGreaterThan(0)
  })

  it('renders the Local Connections section below the connect catalog (SOLUSDEV-72)', () => {
    mockSources([])
    render(<SourcesScreen />)
    expect(screen.getByText('LOCAL CONNECTIONS')).toBeInTheDocument()
    expect(screen.getByText('LOCAL TOOLS (BRIDGE)')).toBeInTheDocument()
  })

  it('a local-bridge tile opens the companion guidance, not a credential flow', async () => {
    mockSources([])
    vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([
      {
        id: 'fusion',
        name: 'Fusion',
        kind: 'Local tool — companion bridge',
        mark: 'Fu',
        mode: 'local-bridge',
        configFields: [],
        selection: null,
        accessModes: null,
        hosted: null,
        localTool: {
          type: 'fusion',
          display_name: 'Fusion',
          hosting: 'vendor-run',
          url_host: '127.0.0.1:27182',
          connect_notice: 'Launch Fusion and enable the MCP server',
          requires: 'companion'
        }
      }
    ])
    render(<SourcesScreen />)
    await userEvent.click(screen.getByText('Fusion'))
    expect(await screen.findByText('Connect Fusion')).toBeInTheDocument()
    expect(screen.getByText('Launch Fusion and enable the MCP server')).toBeInTheDocument()
  })
})
