// Workspace shell: rail navigation, topbar, notifications, toast plumbing,
// and the verify-email banner. SOLUSDEV-152: no demo alerts, no scripted
// magic-moment toast, no fabricated project name.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react'
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

// Populate the topbar project switcher deterministically (its live fetch is
// offline in jsdom). Other tests don't open the switcher, so this is inert.
vi.mock('./useProjectSwitcher', () => ({ useProjectSwitcher: vi.fn() }))

// The rail's install poll (EXT-14). Unmocked calls reject → the hook reports
// offline and renders no entries, which is what every pre-existing test expects.
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources.extensions')>()
  return { ...actual, listProjectExtensions: vi.fn() }
})
// Rail icons: `bom` has one, everything else misses → neutral glyph.
vi.mock('../extensions/pageview/extensionIconAsset', () => ({
  fetchExtensionIconSvg: vi.fn(async (slug: string) =>
    slug === 'bom' ? '<svg viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/></svg>' : null
  )
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
    await userEvent.click(screen.getByText('Team'))
    expect(useShellStore.getState().lastMain).toBe('team')
  })

  it('exposes the project hub and sources in the rail (SOLUSDEV-164)', async () => {
    renderShell()
    await userEvent.click(screen.getByText('Overview'))
    expect(useShellStore.getState().lastMain).toBe('overview')
    // With no project open the hub honestly asks the user to pick one.
    expect(await screen.findByText(/select a project/i)).toBeInTheDocument()
    await userEvent.click(screen.getByText('Sources'))
    expect(useShellStore.getState().lastMain).toBe('sources')
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
    await userEvent.click(screen.getByRole('button', { name: 'Open Experiments' }))
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeInTheDocument()
    // Re-clicking the rail returns to the catalog rather than the stale detail page.
    await userEvent.click(screen.getByLabelText('Store'))
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('clears extension install state on sign-out (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    useExtensionsStore.setState({
      byProject: { p1: { bom: { installed: true, enabled: true, runFrequency: 'daily' } } },
      selectedId: 'bom'
    })
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(useExtensionsStore.getState()).toMatchObject({ byProject: {}, selectedId: null })
    // The durable copy is gone too — nothing for the next user of this workstation to read.
    const raw = JSON.parse(localStorage.getItem('solus_extensions_v1') ?? '{}')
    expect(raw.state?.byProject ?? {}).toEqual({})
  })

  it('switching project from the topbar leaves an open extension detail page (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    await userEvent.click(screen.getByText('Store'))
    await userEvent.click(screen.getByRole('button', { name: 'Open Experiments' }))
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
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Rover MK3' })
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

  it('renders enabled page-view installs directly above the Store, by install time', async () => {
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
    expect(ids.slice(ids.indexOf('rail-team'), ids.indexOf('rail-store') + 1)).toEqual([
      'rail-team',
      'rail-ext-bom',
      'rail-ext-cam',
      'rail-store'
    ])
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
      installsPage([pageInstall('bom', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    await userEvent.click(screen.getByText('Overview'))
    await userEvent.click(await screen.findByLabelText('BOM'))
    expect(screen.getByTestId('ext-page-screen')).toHaveTextContent('page:bom')
    expect(screen.getByTestId('ext-page-screen').parentElement?.parentElement).toHaveAttribute(
      'data-screen-label',
      'Extension'
    )
    expect(screen.getByLabelText('BOM')).toHaveAttribute('data-active', 'true')
    expect(screen.getByLabelText('Overview')).not.toHaveAttribute('data-active')
    // A detail route: the main-screen memory is untouched, so Back knows where to go.
    expect(useShellStore.getState().lastMain).toBe('overview')
    await userEvent.click(screen.getByRole('button', { name: 'Back to shell' }))
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
    expect(screen.getByLabelText('Overview')).toHaveAttribute('data-active', 'true')
  })

  it('hands the page screen a way into the Store', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('bom', '2026-09-01T00:00:00Z')])
    )
    renderShell()
    await userEvent.click(await screen.findByLabelText('BOM'))
    await userEvent.click(screen.getByRole('button', { name: 'Open in Store' }))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
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

  it('renders no entries without an open project', () => {
    useWorkspaceStore.setState({ project: null })
    renderShell()
    expect(railIds().some((id) => id.startsWith('rail-ext-'))).toBe(false)
    expect(vi.mocked(ext.listProjectExtensions)).not.toHaveBeenCalled()
  })

  it('switching project from the topbar leaves an open extension page for Overview', async () => {
    vi.mocked(ext.listProjectExtensions).mockResolvedValue(
      installsPage([pageInstall('bom', '2026-09-01T00:00:00Z')])
    )
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' } })
    renderShell()
    await userEvent.click(await screen.findByLabelText('BOM'))
    expect(screen.getByTestId('ext-page-screen')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
    expect(useShellStore.getState().lastMain).toBe('overview')
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Rover MK3' })
  })
})

describe('WorkspaceShell — no scripted magic-moment toast', () => {
  it('fires no toast after landing on the graph', async () => {
    vi.useFakeTimers()
    try {
      renderShell()
      fireEvent.click(screen.getByText('Context Model'))
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
