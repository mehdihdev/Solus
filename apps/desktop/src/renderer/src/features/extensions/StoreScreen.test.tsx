// SOLUSDEV-235 — the Store catalog page over the server catalog.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StoreScreen, INSTALLED_PREVIEW_COUNT } from './StoreScreen'
import { useExtensionsStore } from './extensionsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as sourcesHook from '../project/useProjectSources'
import * as ext from '../../lib/api/resources.extensions'
import * as bridgeModule from '../../lib/desktopBridge'
import type { Source } from '../../lib/api/resources'
import type { Page } from '../../lib/api/client'
import { catalogItem, detail, installRow, manifest } from './testing/fixtures'

vi.mock('../project/useProjectSources', () => ({ useProjectSources: vi.fn() }))
vi.mock('../../lib/desktopBridge', async (importOriginal) => ({
  ...(await importOriginal<typeof bridgeModule>()),
  getDesktopExtensionsBridge: vi.fn(() => null)
}))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  listExtensions: vi.fn(),
  listProjectExtensions: vi.fn(),
  getExtension: vi.fn(),
  installExtension: vi.fn(),
  patchExtensionInstall: vi.fn(),
  uninstallProjectExtension: vi.fn(),
  fetchExtensionBundle: vi.fn()
}))

function page<T>(data: T[]): Promise<Page<T[]>> {
  return Promise.resolve({ data, meta: { has_next: false, next_cursor: null } })
}

function mockSources(status: sourcesHook.ProjectSourcesStatus, types: string[] = []): void {
  vi.mocked(sourcesHook.useProjectSources).mockReturnValue({
    status,
    sources: types.map((type) => ({ id: type, type }) as Source),
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
}

function named(slug: string, name: string, requires: string[][] = []): ext.ExtensionCatalogItemApi {
  return catalogItem({ slug, name, summary: `${name} summary.`, requires, views: ['widget'] })
}

function installed(slug: string, name: string): ext.ExtensionInstallApi {
  const m = manifest({ extension: { ...manifest().extension, id: slug, name, requires: [] } })
  return installRow({ version: { ...installRow().version, manifest: m } })
}

const INSTALLED = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((s) => [s, `Ext ${s.toUpperCase()}`])

beforeEach(() => {
  vi.clearAllMocks()
  useExtensionsStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Elegoo Robot Test' }, linked: true })
  mockSources('ready')
  vi.mocked(ext.listExtensions).mockImplementation(() =>
    page([
      ...INSTALLED.map(([slug, name]) => named(slug, name)),
      catalogItem(),
      named('can-telemetry', 'CAN Telemetry', [['canbus']]),
      named('fsae', 'FSAE Rules Checker', [['cad', 'eda']]),
      named('datasheets', 'Datasheet Finder', [['eda']])
    ])
  )
  vi.mocked(ext.listProjectExtensions).mockImplementation(() =>
    page(INSTALLED.map(([slug, name]) => installed(slug, name)))
  )
  vi.mocked(ext.getExtension).mockResolvedValue(detail())
})

async function renderStore(): Promise<void> {
  render(<StoreScreen />)
  await waitFor(() => expect(screen.getByTestId('store-installed')).toBeInTheDocument())
  await waitFor(() => expect(screen.queryByText(/Loading the catalog/)).not.toBeInTheDocument())
}

describe('StoreScreen', () => {
  registerStoreCatalogAndRequirementsTests()
  registerStoreNavigationAndLayoutsTests()
})

function registerStoreCatalogAndRequirementsTests(): void {
  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    render(<StoreScreen />)
    expect(screen.getByText('Select a project')).toBeInTheDocument()
  })

  it('previews the installed set and expands to all of them', async () => {
    await renderStore()
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
    const installedGrid = screen.getByTestId('store-installed')
    expect(within(installedGrid).getAllByText('INSTALLED')).toHaveLength(INSTALLED_PREVIEW_COUNT)
    await userEvent.click(screen.getByRole('button', { name: 'See all installed (7)' }))
    expect(within(installedGrid).getAllByText('INSTALLED')).toHaveLength(7)
    await userEvent.click(screen.getByRole('button', { name: 'Show fewer' }))
    expect(within(installedGrid).getAllByText('INSTALLED')).toHaveLength(INSTALLED_PREVIEW_COUNT)
  })

  it('suggests uninstalled extensions with their source requirements', async () => {
    await renderStore()
    const popular = screen.getByTestId('store-popular')
    expect(within(popular).getByText('BOM')).toBeInTheDocument()
    expect(within(popular).getAllByText('NEEDS EDA')).toHaveLength(2)
    expect(within(popular).getByText('NEEDS CANBUS')).toBeInTheDocument()
    expect(within(popular).getByText('NEEDS CAD|EDA')).toBeInTheDocument()
  })

  it('requirements follow what is actually connected', async () => {
    mockSources('ready', ['kicad'])
    await renderStore()
    const popular = screen.getByTestId('store-popular')
    expect(within(popular).getAllByText('AVAILABLE')).toHaveLength(3)
    expect(within(popular).getByText('NEEDS CANBUS')).toBeInTheDocument()
  })

  it('explains when source requirements cannot be evaluated', async () => {
    mockSources('offline')
    await renderStore()
    expect(screen.getByText(/can't see this project's sources/i)).toBeInTheDocument()
  })

  it('says when it is still checking sources rather than flashing unmet requirements as final', async () => {
    mockSources('loading')
    await renderStore()
    expect(screen.getByText(/Checking this project’s connected sources/)).toBeInTheDocument()
  })

  it('shows an empty, honest catalog when the Store API is unreachable', async () => {
    vi.mocked(ext.listExtensions).mockRejectedValue(new TypeError('fetch failed'))
    render(<StoreScreen />)
    expect(await screen.findByText(/can't reach the Store/i)).toBeInTheDocument()
    expect(screen.getByText('Nothing installed in this project yet.')).toBeInTheDocument()
    expect(screen.getByText(/catalog is unavailable/i)).toBeInTheDocument()
  })
}

function registerStoreNavigationAndLayoutsTests(): void {
  it('counts the updates available across installed extensions', async () => {
    vi.mocked(ext.listProjectExtensions).mockImplementation(() =>
      page([
        {
          ...installed('a', 'Ext A'),
          update_available: { version: '2.0.0', widens_permissions: false }
        },
        installed('b', 'Ext B')
      ])
    )
    await renderStore()
    expect(screen.getByText('1 update available')).toBeInTheDocument()
  })

  it('switches between grid and list layouts', async () => {
    await renderStore()
    expect(screen.getByTestId('store-installed')).toHaveAttribute('data-layout', 'grid')
    await userEvent.click(screen.getByRole('radio', { name: 'List view' }))
    expect(screen.getByTestId('store-installed')).toHaveAttribute('data-layout', 'list')
  })

  it('opens an extension in detail, fetching its manifest, and returns to the catalog', async () => {
    await renderStore()
    await userEvent.click(screen.getByRole('button', { name: 'Open BOM' }))
    expect(useExtensionsStore.getState().selectedId).toBe('bom')
    expect(screen.getByRole('heading', { name: 'BOM' })).toBeInTheDocument()
    await waitFor(() => expect(ext.getExtension).toHaveBeenCalledWith('bom'))
    await userEvent.click(screen.getByRole('tab', { name: 'Permissions' }))
    expect(await screen.findByText('Read the workspace graph')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Store' }))
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('does not re-fetch the detail of an installed extension (its pinned manifest is on the row)', async () => {
    await renderStore()
    await userEvent.click(screen.getByRole('button', { name: 'Open Ext A' }))
    expect(screen.getByRole('heading', { name: 'Ext A' })).toBeInTheDocument()
    expect(ext.getExtension).not.toHaveBeenCalled()
  })

  it('falls back to the catalog for a stale selection', async () => {
    useExtensionsStore.getState().select('gone')
    await renderStore()
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('opens the create-extension dialog', async () => {
    await renderStore()
    await userEvent.click(screen.getByRole('button', { name: /Create extension/ }))
    expect(screen.getByRole('heading', { name: 'Create an extension' })).toBeInTheDocument()
  })
}
