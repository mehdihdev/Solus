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
import * as githubHook from '../onboarding/useGithubConnect'
import * as edaHook from '../onboarding/useEdaConnect'

vi.mock('./useProjectSources', () => ({ useProjectSources: vi.fn() }))
vi.mock('../onboarding/useIntegrationCatalog', () => ({ useIntegrationCatalog: vi.fn() }))
vi.mock('../onboarding/useGithubConnect', () => ({ useGithubConnect: vi.fn() }))
vi.mock('../onboarding/useEdaConnect', () => ({ useEdaConnect: vi.fn() }))

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
    { id: 'github', name: 'GitHub', kind: 'Code', mark: 'GH', mode: 'github-oauth' },
    { id: 'kicad', name: 'KiCad', kind: 'PCB', mark: 'Ki', mode: 'export-file' }
  ])
  vi.mocked(githubHook.useGithubConnect).mockReturnValue({ start: vi.fn(), chooseRepo: vi.fn() })
  vi.mocked(edaHook.useEdaConnect).mockReturnValue({ start: vi.fn() })
})

describe('SourcesScreen', () => {
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
    expect(screen.getByText(/can't reach its API/i)).toBeInTheDocument()
  })
})
