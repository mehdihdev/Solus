// Workspace shell: rail navigation, topbar, notifications, toast plumbing,
// and the verify-email banner. SOLUSDEV-152: no demo alerts, no scripted
// magic-moment toast, no fabricated project name.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { WorkspaceShell } from './WorkspaceShell'
import { useShellStore } from './shellStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as switcherHook from './useProjectSwitcher'
import { useExtensionsStore } from '../extensions/extensionsStore'
import * as ext from '../../lib/api/resources.extensions'
import type { Page } from '../../lib/api/client'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import { catalogItem, installRow, manifest } from '../extensions/testing/fixtures'
import { useDevExtensionsStore } from '../devExtensions/devExtensionsStore'
import { usePinsStore } from '../extensions/pinsStore'
import { clearWorkspaceGraphCache } from '../graph/useWorkspaceGraph'

// Populate the topbar project switcher deterministically (its live fetch is
// offline in jsdom). Other tests don't open the switcher, so this is inert.
vi.mock('./useProjectSwitcher', () => ({ useProjectSwitcher: vi.fn() }))

// Sign-out must drop the retained graph snapshots (WS-01); the module's own clear is the seam.
vi.mock('../graph/useWorkspaceGraph', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../graph/useWorkspaceGraph')>()),
  clearWorkspaceGraphCache: vi.fn()
}))

// The Store reads the server catalog and install rows (EXT-17) and the rail
// polls the same install list (EXT-14): one mock serves both. beforeEach seeds
// one installed "Experiments" row so the Store detail page is reachable; the
// rail tests reset the install mock and seed page-view rows of their own.
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  listExtensions: vi.fn(),
  listProjectExtensions: vi.fn(),
  getExtension: vi.fn(),
  listExtensionPins: vi.fn(async () => []),
  pinExtension: vi.fn(),
  unpinExtension: vi.fn()
}))
const experiments = manifest({
  extension: { ...manifest().extension, id: 'experiments', name: 'Experiments', requires: [] }
})
// Rail icons: `bom` has one, everything else misses → neutral glyph.
vi.mock('../extensions/pageview/extensionIconAsset', () => ({
  fetchExtensionIconSvg: vi.fn(async (slug: string) =>
    slug === 'bom' ? '<svg viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/></svg>' : null
  )
}))
// The BOM page's data hook reads the bundle's routes; the shell tests only
// prove the first-party page is what mounts for an installed `bom`.
vi.mock('../bom/useBom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../bom/useBom')>()),
  useBom: vi.fn(() => ({
    status: 'not_installed',
    view: null,
    actions: {
      addRow: vi.fn(),
      patchRow: vi.fn(),
      setState: vi.fn(),
      removeRow: vi.fn(),
      exportCsv: vi.fn(),
      refresh: vi.fn()
    }
  }))
}))
// The page screen resolves bundles through the desktop bridge; here it only
// needs to prove the shell mounted it with the right slug and callbacks.
vi.mock('../extensions/pageview/ExtensionPageScreen', () => ({
  ExtensionPageScreen: ({
    slug,
    onBack,
    onOpenStore
  }: {
    slug: string
    onBack?: () => void
    onOpenStore?: () => void
  }) => (
    <div data-testid="ext-page-screen">
      page:{slug}
      <button onClick={onBack}>Back to shell</button>
      <button onClick={onOpenStore}>Open in Store</button>
    </div>
  )
}))

function pageInstall(slug: string, installedAt: string, enabled = true): ext.ExtensionInstallApi {
  const base = fakeInstall({ installed_at: installedAt, enabled })
  return {
    ...base,
    extension: { ...base.extension, slug },
    version: {
      ...base.version,
      manifest: fakeManifest({
        views: { page: { entry: 'page.html', icon: `${slug}.svg`, label: slug.toUpperCase() } }
      })
    }
  }
}

function installsPage(rows: ext.ExtensionInstallApi[]): Page<ext.ExtensionInstallApi[]> {
  return { data: rows, meta: { has_next: false, next_cursor: null } }
}

/** Rail buttons in DOM order (the rail's ids are `rail-<screen>` / `rail-ext-<slug>`). */
function railIds(): string[] {
  return Array.from(document.querySelectorAll('[id^="rail-"]')).map((el) => el.id)
}

function renderShell(): ReturnType<typeof render> {
  return render(
    <MemoryRouter>
      <WorkspaceShell />
    </MemoryRouter>
  )
}

beforeEach(() => {
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useExtensionsStore.getState().reset()
  vi.mocked(ext.listExtensions).mockResolvedValue({
    data: [
      catalogItem({ slug: 'experiments', name: 'Experiments', requires: [], views: ['widget'] })
    ],
    meta: { has_next: false, next_cursor: null }
  })
  vi.mocked(ext.listProjectExtensions).mockResolvedValue({
    data: [installRow({ version: { ...installRow().version, manifest: experiments } })],
    meta: { has_next: false, next_cursor: null }
  })
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'dev@example.dev' },
    onboarded: true
  })
  vi.mocked(switcherHook.useProjectSwitcher).mockReturnValue({
    status: 'ready',
    groups: [
      {
        team: { team_id: 't1', name: 'Acme', role: 'member', is_personal: false },
        projects: [
          {
            id: 'p2',
            team_id: 't1',
            name: 'Rover MK3',
            description: null,
            archived_at: null,
            created_at: '',
            updated_at: ''
          }
        ]
      }
    ]
  } as ReturnType<typeof switcherHook.useProjectSwitcher>)
})

describe('WorkspaceShell — chrome', () => {
  it('opens on Home with an honest no-project topbar fallback', async () => {
    renderShell()
    // Authenticated sessions now attempt a real fetch first (spinner), then
    // settle offline in jsdom where the API is unreachable.
    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument()
    expect(screen.getByText('No project')).toBeInTheDocument()
    // Signed-in + unreachable API must never read as "sign in".
    expect(screen.getByText(/can't reach its API/)).toBeInTheDocument()
    expect(screen.queryByText(/Sign in to Solus/)).not.toBeInTheDocument()
  })

  it('shows the real project name when one is linked', () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    renderShell()
    expect(screen.getByText('Rover MK3')).toBeInTheDocument()
  })

  it('navigates between screens from the rail', async () => {
    renderShell()
    await userEvent.click(screen.getByText('Live Bench'))
    expect(useShellStore.getState().lastMain).toBe('bench')
    // The Team screen was folded into Home (SOLUSDEV-244 / HOME H5): no rail
    // item, no menu entry.
    expect(screen.queryByText('Team')).toBeNull()
    await userEvent.click(screen.getByText('Home'))
    expect(useShellStore.getState().lastMain).toBe('home')
  })

  it('mounts no corner orb — SOL is the rail item and the SOL window (SOLUSDEV-252)', () => {
    renderShell()
    expect(screen.getByLabelText('SOL')).toBeInTheDocument()
    expect(screen.queryByLabelText('Ask SOL')).toBeNull()
    expect(screen.queryByTitle('Ask SOL')).toBeNull()
  })

  it('no longer carries the Overview hub or the Sources page in the rail (SOLUSDEV-244)', () => {
    renderShell()
    expect(screen.queryByLabelText('Overview')).toBeNull()
    expect(screen.queryByLabelText('Sources')).toBeNull()
    expect(screen.getByLabelText('Workspace')).toBeInTheDocument()
  })
})

describe('WorkspaceShell — Store and project switching (SOLUSDEV-235)', () => {
  it('exposes the Store in the rail and breadcrumbs the open extension (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    renderShell()
    // The Store button is the one emphasised rail item (accent border + tint).
    expect(screen.getByLabelText('Store')).toHaveAttribute('data-emphasis', 'true')
    await userEvent.click(screen.getByText('Store'))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Open Experiments' }))
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeInTheDocument()
    // Re-clicking the rail returns to the catalog rather than the stale detail page.
    await userEvent.click(screen.getByLabelText('Store'))
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('clears the Store selection on sign-out (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    useExtensionsStore.setState({ selectedId: 'bom' })
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(useExtensionsStore.getState().selectedId).toBeNull()
    // Install state is the server's now — nothing durable is left on this workstation.
    expect(localStorage.getItem('solus_extensions_v1')).toBeNull()
  })

  it('switching project from the topbar leaves an open extension detail page (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    await userEvent.click(screen.getByText('Store'))
    await userEvent.click(await screen.findByRole('button', { name: 'Open Experiments' }))
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('offers a project switcher in the topbar (SOLUSDEV-164)', () => {
    renderShell()
    expect(screen.getByRole('button', { name: /switch project/i })).toBeInTheDocument()
  })

  it('draws the title row and menu row above the rail (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    renderShell()
    // The project pill lives in the title row; the menus in the row below.
    expect(screen.getByTestId('title-bar')).toContainElement(
      screen.getByRole('button', { name: /switch project/i })
    )
    for (const label of ['Solus', 'View', 'Robot', 'Help'])
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    // View → Store navigates like the rail does.
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Store' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('switching project from the topbar re-scopes the current screen without navigating', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    // Move to a project-scoped screen, then switch project from the topbar.
    await userEvent.click(screen.getByText('Live Bench'))
    expect(useShellStore.getState().lastMain).toBe('bench')
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    // Context changed, but we stayed on Live Bench (no jump to Overview).
    expect(useWorkspaceStore.getState().project).toEqual({
      id: 'p2',
      name: 'Rover MK3',
      teamId: 't1'
    })
    // The project's team becomes the active team (SOLUSDEV-242).
    expect(useWorkspaceStore.getState().teamId).toBe('t1')
    expect(useShellStore.getState().lastMain).toBe('bench')
    // The topbar now shows the switched-to project as the active context.
    expect(screen.getByText('Rover MK3')).toBeInTheDocument()
  })
})

describe('WorkspaceShell — notifications', () => {
  it('shows no unread badge when offline — alerts are never fabricated', () => {
    renderShell()
    expect(screen.queryByText('2')).not.toBeInTheDocument()
  })

  it('offline bell opens an honest popover instead of demo alerts', async () => {
    renderShell()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    // Signed in (beforeEach) + unreachable API → the honest unreachable note.
    expect(screen.getByText(/can't reach its API right now/)).toBeInTheDocument()
    expect(screen.queryByText(/Motor driver swap/)).not.toBeInTheDocument()
  })

  it('offline bell shows the sign-in nudge for signed-out sessions', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    renderShell()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(screen.getByText(/Sign in to Solus to see notifications/)).toBeInTheDocument()
  })

  it('renders no fabricated robot data anywhere in the shell', () => {
    const { container } = renderShell()
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/Priya|DRV8316C|U4 swap/)
  })
})

describe('WorkspaceShell — extension rail (SOLUSDEV-235 / EXT-14)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    vi.mocked(ext.listProjectExtensions).mockReset()
  })

  it('renders enabled page-view installs after the Store behind a separator, by install time (STORE ST3)', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([
        pageInstall('cam', '2026-09-02T00:00:00Z'),
        pageInstall('bom', '2026-09-01T00:00:00Z'),
        pageInstall('off', '2026-09-01T00:00:00Z', false)
      ])
    )
    renderShell()
    await screen.findByLabelText('BOM')
    const ids = railIds()
    expect(ids.slice(ids.indexOf('rail-sol'), ids.indexOf('rail-ext-cam') + 1)).toEqual([
      'rail-sol',
      'rail-store',
      'rail-ext-bom',
      'rail-ext-cam'
    ])
    // The separator sits between the Store and the tabs, and only when there are tabs.
    const separator = screen.getByTestId('rail-separator')
    expect(separator.compareDocumentPosition(screen.getByLabelText('Store'))).toBe(
      Node.DOCUMENT_POSITION_PRECEDING
    )
    expect(separator.compareDocumentPosition(screen.getByLabelText('BOM'))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
    expect(screen.queryByLabelText('OFF')).toBeNull()
    expect(screen.getByLabelText('CAM')).toHaveAttribute('title', 'CAM')
    // The Store keeps its emphasis; entries are ordinary rail items.
    expect(screen.getByLabelText('Store')).toHaveAttribute('data-emphasis', 'true')
    expect(screen.getByLabelText('BOM')).not.toHaveAttribute('data-emphasis')
  })

  it('draws the reduced manifest icon, or the neutral glyph when the icon is missing', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([
        pageInstall('bom', '2026-09-01T00:00:00Z'),
        pageInstall('cam', '2026-09-02T00:00:00Z')
      ])
    )
    renderShell()
    const bom = await screen.findByLabelText('BOM')
    await waitFor(() => expect(bom.querySelector('[data-testid="extension-icon"]')).not.toBeNull())
    const cam = screen.getByLabelText('CAM')
    expect(cam.querySelector('[data-testid="extension-icon"]')).toBeNull()
    expect(cam.querySelector('[data-testid="rail-ext-fallback"]')).not.toBeNull()
  })

  it('opens the extension page from its rail entry and marks the entry active', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('cam', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    await userEvent.click(screen.getByText('Workspace'))
    await userEvent.click(await screen.findByLabelText('CAM'))
    expect(screen.getByTestId('ext-page-screen')).toHaveTextContent('page:cam')
    expect(screen.getByTestId('ext-page-screen').parentElement?.parentElement).toHaveAttribute(
      'data-screen-label',
      'Extension'
    )
    expect(screen.getByLabelText('CAM')).toHaveAttribute('data-active', 'true')
    expect(screen.getByLabelText('Workspace')).not.toHaveAttribute('data-active')
    // A detail route: the main-screen memory is untouched, so Back knows where to go.
    expect(useShellStore.getState().lastMain).toBe('workspace')
    await userEvent.click(screen.getByRole('button', { name: 'Back to shell' }))
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
    expect(screen.getByLabelText('Workspace')).toHaveAttribute('data-active', 'true')
  })

  it('hands the page screen a way into the Store', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('cam', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    await userEvent.click(await screen.findByLabelText('CAM'))
    await userEvent.click(screen.getByRole('button', { name: 'Open in Store' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    // STORE ST3: it lands on THIS extension's detail page, one step from the catalog.
    expect(useExtensionsStore.getState().selectedId).toBe('cam')
    expect(screen.getByLabelText('Back to Store')).toBeInTheDocument()
  })
})

describe('WorkspaceShell — developer registrations in the rail (EXT-20)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    vi.mocked(ext.listProjectExtensions).mockReset()
    useDevExtensionsStore.getState().reset()
    useDevExtensionsStore.setState({
      entries: {
        lab: {
          manifest: fakeManifest({
            extension: { ...fakeManifest().extension, id: 'lab', name: 'Lab' },
            views: { page: { entry: 'page.html', icon: 'lab.svg', label: 'Lab (dev)' } }
          }),
          devPath: '/code/lab',
          loadedAt: '2026-09-05T00:00:00Z',
          acknowledged: true,
          problems: []
        }
      }
    })
  })

  it('draws a page-view dev registration after the installs with a DEV corner mark and the neutral glyph', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('bom', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    const lab = await screen.findByLabelText('Lab (dev)')
    await screen.findByLabelText('BOM')
    const ids = railIds()
    expect(ids.slice(ids.indexOf('rail-sol'), ids.indexOf('rail-ext-lab') + 1)).toEqual([
      'rail-sol',
      'rail-store',
      'rail-ext-bom',
      'rail-ext-lab'
    ])
    expect(lab.querySelector('[data-testid="rail-dev-mark"]')).toHaveTextContent('DEV')
    expect(lab.querySelector('[data-testid="rail-ext-fallback"]')).not.toBeNull()
    expect(screen.getByLabelText('BOM').querySelector('[data-testid="rail-dev-mark"]')).toBeNull()
    useDevExtensionsStore.getState().reset()
  })
})

describe('WorkspaceShell — extension rail limits and project scope (EXT-14)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    vi.mocked(ext.listProjectExtensions).mockReset()
  })

  it('caps the rail at eight entries — the rest stay in the Store', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage(
        Array.from({ length: 10 }, (_, i) =>
          pageInstall(`ext${i}`, `2026-09-01T00:00:${String(i).padStart(2, '0')}Z`)
        )
      )
    )
    renderShell()
    await screen.findByLabelText('EXT0')
    expect(railIds().filter((id) => id.startsWith('rail-ext-'))).toHaveLength(8)
    expect(screen.queryByLabelText('EXT9')).toBeNull()
  })

  it('renders no entries and no separator without an open project', () => {
    useWorkspaceStore.setState({ project: null })
    renderShell()
    expect(railIds().some((id) => id.startsWith('rail-ext-'))).toBe(false)
    expect(screen.queryByTestId('rail-separator')).toBeNull()
    expect(vi.mocked(ext.listProjectExtensions)).not.toHaveBeenCalled()
  })

  it('switching project from the topbar leaves an open extension page for Workspace', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('cam', '2026-09-01T00:00:00Z')])
    )
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' } })
    renderShell()
    await userEvent.click(await screen.findByLabelText('CAM'))
    expect(screen.getByTestId('ext-page-screen')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
    expect(useShellStore.getState().lastMain).toBe('workspace')
    expect(useWorkspaceStore.getState().project).toMatchObject({ id: 'p2', name: 'Rover MK3' })
  })
})

function pinRow(slug: string, page = true): ext.ExtensionPinApi {
  return {
    slug,
    name: slug.toUpperCase(),
    verified: true,
    publisher: { display_name: 'Solus' },
    version: '1.2.0',
    views: page ? ['page'] : ['widget'],
    page: page ? { label: slug.toUpperCase(), icon: `${slug}.svg` } : null,
    pinned_at: '2026-09-06T00:00:00Z'
  }
}

describe('WorkspaceShell — pins and first-party pages (STORE ST3 / ST4)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    vi.mocked(ext.listProjectExtensions).mockReset()
    usePinsStore.getState().reset()
  })

  it('right-click on a tab offers "Pin for all projects" and pins through the server', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('cam', '2026-09-01T00:00:00Z')])
    )
    vi.mocked(ext.pinExtension).mockResolvedValue(pinRow('cam'))
    renderShell()
    const cam = await screen.findByLabelText('CAM')
    expect(cam.querySelector('[data-testid="rail-pin-mark"]')).toBeNull()
    fireEvent.contextMenu(cam, { clientX: 40, clientY: 200 })
    await userEvent.click(screen.getByRole('menuitem', { name: 'Pin for all projects' }))
    expect(ext.pinExtension).toHaveBeenCalledWith('cam')
    await waitFor(() =>
      expect(
        screen.getByLabelText('CAM').querySelector('[data-testid="rail-pin-mark"]')
      ).not.toBeNull()
    )
    // Now the menu offers the reverse.
    fireEvent.contextMenu(screen.getByLabelText('CAM'), { clientX: 40, clientY: 200 })
    expect(screen.getByRole('menuitem', { name: 'Unpin from all projects' })).toBeInTheDocument()
  })

  it('a pinned extension shows in a project where it is not installed, and its tab is honest', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(installsPage([]))
    vi.mocked(ext.listExtensionPins).mockResolvedValue([pinRow('cam')])
    renderShell()
    const cam = await screen.findByLabelText('CAM')
    expect(screen.getByTestId('rail-separator')).toBeInTheDocument()
    expect(cam).toHaveAttribute('data-dimmed', 'true')
    expect(cam).toHaveAttribute('title', 'CAM — not installed here')
    await userEvent.click(cam)
    expect(screen.getByTestId('pinned-not-installed')).toHaveTextContent(
      "CAM isn't installed in Rover MK3"
    )
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
    // "Install in this project" lands on the Store's detail page for that slug.
    await userEvent.click(screen.getByRole('button', { name: 'Install in this project' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(useExtensionsStore.getState().selectedId).toBe('cam')
  })

  it('an installed first-party bundle opens its in-repo page, not a frame', async () => {
    const row = pageInstall('bom', '2026-09-01T00:00:00Z')
    const firstParty = {
      ...row,
      version: {
        ...row.version,
        manifest: { ...row.version.manifest, backend: { capability: 'bom', routes: true } }
      }
    }
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(installsPage([firstParty]))
    renderShell()
    await userEvent.click(await screen.findByLabelText('BOM'))
    expect(screen.getByTestId('bom-screen')).toBeInTheDocument()
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
  })

  it('a COMMUNITY bundle that carries a first-party slug still gets the sandboxed frame', async () => {
    // The slug alone never picks the trusted page (security review M2): only a
    // pinned manifest with a first-party table does, and the publish gate keeps
    // those tables staff-only.
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('bom', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    await userEvent.click(await screen.findByLabelText('BOM'))
    expect(screen.getByTestId('ext-page-screen')).toHaveTextContent('page:bom')
    expect(screen.queryByTestId('bom-screen')).toBeNull()
  })

  it('the context menu opens the Store detail and a dev registration cannot be pinned', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(installsPage([]))
    useDevExtensionsStore.setState({
      entries: {
        lab: {
          manifest: fakeManifest({
            extension: { ...fakeManifest().extension, id: 'lab', name: 'Lab' },
            views: { page: { entry: 'page.html', icon: 'lab.svg', label: 'Lab (dev)' } }
          }),
          devPath: '/code/lab',
          loadedAt: '2026-09-05T00:00:00Z',
          acknowledged: true,
          problems: []
        }
      }
    })
    renderShell()
    fireEvent.contextMenu(await screen.findByLabelText('Lab (dev)'), { clientX: 40, clientY: 200 })
    expect(screen.getByRole('menuitem', { name: /Pin for all projects/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
    await userEvent.click(screen.getByRole('menuitem', { name: 'Open in Store' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(useExtensionsStore.getState().selectedId).toBe('lab')
    useDevExtensionsStore.getState().reset()
  })

  it('a Store toast with a slug lands on that extension’s detail page', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(installsPage([]))
    renderShell()
    act(() =>
      useShellStore.getState().setToast({
        kind: 'ok',
        title: 'BOM is now available',
        body: 'An EDA tool is connected.',
        action: 'View',
        screen: 'store',
        extensionSlug: 'bom'
      })
    )
    const toast = screen.getByText('BOM is now available').closest('[class~="toast-in"]')
    await userEvent.click(within(toast as HTMLElement).getByRole('button', { name: 'View' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(useExtensionsStore.getState().selectedId).toBe('bom')
  })

  it('clears the pins on sign-out', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(installsPage([]))
    vi.mocked(ext.listExtensionPins).mockResolvedValue([pinRow('cam')])
    renderShell()
    await screen.findByLabelText('CAM')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(usePinsStore.getState().pins).toEqual([])
  })
})

describe('WorkspaceShell — no scripted magic-moment toast', () => {
  it('fires no toast after landing on the graph', async () => {
    vi.useFakeTimers()
    try {
      renderShell()
      fireEvent.click(screen.getByText('Workspace'))
      await act(async () => {
        vi.advanceTimersByTime(6000)
      })
      expect(useShellStore.getState().toast).toBeNull()
      expect(screen.queryByText('SOL caught a cross-domain break')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('WorkspaceShell — email verification banner', () => {
  it('shows the verify-email banner when the email is unverified', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: false },
      onboarded: true
    })
    renderShell()
    expect(screen.getByRole('alert')).toHaveTextContent(/Verify your email/)
    expect(screen.getByText('Resend email')).toBeInTheDocument()
  })

  it('hides the banner for a verified email', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: true },
      onboarded: true
    })
    renderShell()
    expect(screen.queryByText(/Verify your email/)).not.toBeInTheDocument()
  })

  it('resends the verification email on request', async () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: false },
      onboarded: true
    })
    renderShell()
    await userEvent.click(screen.getByText('Resend email'))
    expect(screen.getByText('Verification email sent.')).toBeInTheDocument()
  })
})

describe('WorkspaceShell — nothing carries across a project switch (SOLUSDEV-242)', () => {
  it('drops a toast raised under the previous project', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    act(() => {
      useShellStore.getState().setToast({
        title: 'SOL replied',
        body: 'open SOL to read it',
        action: 'View',
        screen: 'sol'
      })
    })
    expect(screen.getByText('SOL replied')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    expect(useShellStore.getState().toast).toBe(null)
    expect(screen.queryByText('SOL replied')).toBeNull()
  })

  it('leaves an open alert detail for Workspace — the alert id belonged to the previous project', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    act(() => {
      useShellStore
        .getState()
        .setToast({ title: 'Alert', body: 'USB-C port blocked', action: 'View', alertId: 'al-1' })
    })
    // The toast's View (the menu bar has a 'View' menu too; the toast renders last).
    await userEvent.click(screen.getAllByRole('button', { name: 'View' }).at(-1) as HTMLElement)
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    expect(useShellStore.getState().lastMain).toBe('workspace')
    expect(document.querySelector('[data-screen-label="Workspace"]')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /back/i })).toBeNull()
  })

  it('clears the retained graph snapshots on sign-out, like the focus cache (WS-01)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    vi.mocked(clearWorkspaceGraphCache).mockClear()
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(clearWorkspaceGraphCache).toHaveBeenCalled())
  })
})
