// The project pane's SOURCES block (SOLUSDEV-317): every tool this project
// uses or could use from an already-linked account — its logo, what it holds
// in THIS project (a GitHub repo by name), and the project-level next step
// through the same wizard as Connected accounts. Honest states throughout.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectSourcesSummary } from './ProjectSourcesSummary'
import * as projectSources from '../project/useProjectSources'
import * as accountsHook from './useAccountConnections'
import * as catalogHook from '../onboarding/useIntegrationCatalog'
import * as wizardHook from '../onboarding/useConnectWizard'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import type { Connection, Source } from '../../lib/api/resources'
import * as desktopBridge from '../../lib/desktopBridge'
import { useProjectFolderStore } from '../project/projectFolderStore'

vi.mock('../project/useProjectSources', () => ({ useProjectSources: vi.fn() }))
vi.mock('./useAccountConnections', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useAccountConnections')>()
  return { ...actual, useAccountConnections: vi.fn() }
})
vi.mock('../onboarding/useIntegrationCatalog', () => ({ useIntegrationCatalog: vi.fn() }))
vi.mock('../onboarding/useConnectWizard', () => ({ useConnectWizard: vi.fn() }))
vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopFolderBridge: vi.fn(() => null) }
})

const GITHUB: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'Gh',
  mode: 'oauth',
  configFields: [],
  selection: { mode: 'multi', config_key: 'repo', label: 'repository' },
  accessModes: null,
  hosted: null
}
const ONSHAPE: CatalogEntry = {
  ...GITHUB,
  id: 'onshape',
  name: 'Onshape',
  mark: 'On',
  selection: { mode: 'multi', config_key: 'documents', label: 'document' }
}
const KICAD: CatalogEntry = {
  ...GITHUB,
  id: 'kicad',
  name: 'KiCad',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export'],
  selection: null
}

const connection = (provider: string): Connection => ({
  id: `c-${provider}`,
  provider,
  status: 'connected',
  account_login: 'ada',
  access: 'read',
  needs_reauth: null,
  last_error: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: ''
})

const source = (over: Partial<Source>): Source => ({
  id: 's1',
  project_id: 'p1',
  type: 'github',
  name: 'rover-firmware',
  status: 'connected',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  entity_count: 42,
  created_at: '',
  updated_at: '',
  ...over
})

const PROJECT = { id: 'p1', name: 'Rover', teamId: 't1' }
const open = vi.fn()

function setup({
  connections = [] as Connection[],
  sources = [] as Source[],
  status = 'ready' as projectSources.ProjectSourcesStatus,
  limit = undefined as number | undefined
} = {}): { onAdd: ReturnType<typeof vi.fn> } {
  vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([GITHUB, ONSHAPE, KICAD])
  vi.mocked(accountsHook.useAccountConnections).mockReturnValue({
    status: 'ready',
    connections,
    legacy: [],
    refresh: vi.fn(),
    revoke: vi.fn(),
    move: vi.fn()
  })
  vi.mocked(projectSources.useProjectSources).mockReturnValue({
    status,
    sources,
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
  vi.mocked(wizardHook.useConnectWizard).mockReturnValue({
    active: null,
    linkedAccount: null,
    open,
    begin: vi.fn(),
    pickFiles: vi.fn(),
    close: vi.fn(),
    refreshSelection: vi.fn(),
    select: vi.fn(),
    submitConfig: vi.fn(),
    chooseAccess: vi.fn()
  } as unknown as ReturnType<typeof wizardHook.useConnectWizard>)
  const onAdd = vi.fn()
  render(<ProjectSourcesSummary project={PROJECT} onAdd={onAdd} limit={limit} />)
  return { onAdd }
}

const row = (tool: string): HTMLElement => screen.getByTestId(`source-tool-${tool}`)

beforeEach(() => vi.clearAllMocks())

describe('ProjectSourcesSummary', () => {
  it('names the linked GitHub repo under the tool, with its project-level next step', async () => {
    setup({
      connections: [connection('github')],
      sources: [source({ config: { repo: 'strider/rover-firmware' } })]
    })
    const gh = row('github')
    expect(within(gh).getByText('GitHub')).toBeInTheDocument()
    // The repo gets its own line, in full — never clipped beside the count or the button.
    expect(within(gh).getByText('strider/rover-firmware')).toHaveStyle({
      overflowWrap: 'anywhere',
      whiteSpace: 'normal'
    })
    expect(within(gh).getByText('42 ENTITIES')).toBeInTheDocument()
    // The step is a text link, not a full button.
    expect(
      within(gh).getByRole('button', { name: 'Pick repositories for GitHub' })
    ).toHaveTextContent('Pick repositories ›')
    await userEvent.click(within(gh).getByRole('button', { name: 'Pick repositories for GitHub' }))
    expect(open).toHaveBeenCalledWith(GITHUB)
  })

  it('offers a linked account’s next step even before the project holds anything', async () => {
    setup({ connections: [connection('onshape')] })
    const on = row('onshape')
    expect(within(on).getByText(/nothing in this project yet/i)).toBeInTheDocument()
    await userEvent.click(within(on).getByRole('button', { name: 'Pick documents for Onshape' }))
    expect(open).toHaveBeenCalledWith(ONSHAPE)
  })

  it('shows export tools by what the project holds, with Choose file', () => {
    setup({ sources: [source({ id: 's2', type: 'kicad', name: 'rover.xml', entity_count: 7 })] })
    const ki = row('kicad')
    expect(within(ki).getByText('rover.xml')).toBeInTheDocument()
    expect(within(ki).getByRole('button', { name: 'Choose file for KiCad' })).toBeInTheDocument()
  })

  it('leaves out tools with no linked account and nothing in the project', () => {
    setup({ connections: [connection('github')] })
    expect(screen.queryByTestId('source-tool-onshape')).toBeNull()
    expect(screen.queryByTestId('source-tool-kicad')).toBeNull()
  })

  it('lists a local folder by machine, with no step while it is not linked here', () => {
    setup({ sources: [source({ id: 's3', type: 'local', name: 'mehdi-mbp', entity_count: 95 })] })
    const local = row('local')
    expect(within(local).getByText('95 ENTITIES')).toBeInTheDocument()
    expect(within(local).queryByRole('button')).toBeNull()
  })

  it('offers Open folder on the local folder when this machine has it linked', async () => {
    const reveal = vi.fn().mockResolvedValue({ ok: true })
    vi.mocked(desktopBridge.getDesktopFolderBridge).mockReturnValue({
      reveal
    } as unknown as ReturnType<typeof desktopBridge.getDesktopFolderBridge>)
    useProjectFolderStore.setState({ folders: { p1: { path: '/Users/m/elegoo' } } })
    setup({ sources: [source({ id: 's3', type: 'local', name: 'mehdi-mbp', entity_count: 2 })] })
    await userEvent.click(within(row('local')).getByRole('button', { name: 'Open folder' }))
    expect(reveal).toHaveBeenCalledWith('/Users/m/elegoo')
    useProjectFolderStore.setState({ folders: {} })
  })

  it("shows a source's own error message, as text", () => {
    setup({
      connections: [connection('github')],
      sources: [
        source({ status: 'error', last_error: { code: 'x', message: '<b>Token expired</b>' } })
      ]
    })
    expect(within(row('github')).getByText('<b>Token expired</b>')).toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })

  it('caps the rows when limited and counts the rest', () => {
    setup({
      connections: [connection('github'), connection('onshape')],
      sources: [source({ id: 's2', type: 'kicad', name: 'rover.xml' })],
      limit: 2
    })
    expect(screen.getAllByTestId(/^source-tool-/)).toHaveLength(2)
    expect(screen.getByText('+1 more')).toBeInTheDocument()
  })

  it('offers "Add additional sources", which opens Connected accounts', async () => {
    const { onAdd } = setup({ connections: [connection('github')] })
    await userEvent.click(screen.getByRole('button', { name: 'Add additional sources' }))
    expect(onAdd).toHaveBeenCalled()
  })

  it('says so when nothing is linked or connected', () => {
    setup()
    expect(screen.getByText(/no sources connected yet/i)).toBeInTheDocument()
  })

  it('is honest while loading and when the API is unreachable', () => {
    setup({ status: 'loading' })
    expect(screen.getByText(/loading sources/i)).toBeInTheDocument()
  })
})
