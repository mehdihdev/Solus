// SOLUSDEV-235 / EXT-13 — the page screen: header facts per state, Open in
// window gating, the no-project empty state, and the wireflow §2 state cards.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { fakeBridgeDeps } from '../host/testing/fakeBridgeDeps'
import { fakeBridge, fakeBundleDeps, fakeInstall, fakeManifest } from '../frame/testing/fixtures'
import type { InstalledBundleState } from '../frame/installedBundle'
import { ExtensionPageScreen, type ExtensionPageScreenProps } from './ExtensionPageScreen'

const SVG = '<svg viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/></svg>'
const iconTransport = {
  fetchImpl: async () => new Response(SVG, { headers: { 'content-type': 'image/svg+xml' } }),
  getToken: async () => null
}

// The store is (re)set in beforeEach only: an afterEach reset would re-render
// still-mounted subscribers before Testing Library's cleanup runs.
beforeEach(() => {
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
})

/** Every render gets a hermetic icon transport so no test leaks a fetch past its end. */
function renderPage(props: Partial<ExtensionPageScreenProps> = {}): void {
  render(
    <ExtensionPageScreen
      slug="bom"
      bundleDeps={fakeBundleDeps()}
      bridgeDeps={fakeBridgeDeps()}
      iconTransport={iconTransport}
      {...props}
    />
  )
}

describe('ExtensionPageScreen', () => {
  it('shows the empty state without an open project', () => {
    useWorkspaceStore.setState({ project: null })
    renderPage()
    expect(screen.getByText('Select a project')).toBeInTheDocument()
    expect(screen.queryByTestId('ext-page-screen')).toBeNull()
  })

  it('renders the header immediately, then fills in publisher, version, icon and the frame', async () => {
    const openWindow = vi.fn<(state: InstalledBundleState) => Promise<boolean>>(async () => true)
    renderPage({ openWindow })
    expect(screen.getByTestId('ext-page-screen').className).toContain('screen-in')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('bom')
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('BOM'))
    expect(screen.getByTestId('ext-page-header')).toHaveTextContent('by Solus · v1.2.0')
    expect(screen.getByRole('img', { name: 'Verified by Solus' })).toBeInTheDocument()
    expect(screen.queryByTestId('dev-badge')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('extension-icon')).toBeInTheDocument())
    expect(screen.getByTestId('extension-frame').getAttribute('src')).toBe(
      'solus-ext://bom/1.2.0/page.html'
    )
    screen.getByRole('button', { name: /Open in window/ }).click()
    await waitFor(() => expect(openWindow).toHaveBeenCalledTimes(1))
    expect(openWindow.mock.calls[0]?.[0]).toMatchObject({ status: 'ready', version: '1.2.0' })
  })

  it('hides Open in window when the manifest has no window view', async () => {
    const install = fakeInstall()
    const manifest = fakeManifest({
      views: { page: { entry: 'p.html', icon: 'i.svg', label: 'B' } }
    })
    const deps = fakeBundleDeps({
      listInstalls: async () => [{ ...install, version: { ...install.version, manifest } }]
    })
    renderPage({ bundleDeps: deps })
    await waitFor(() => expect(screen.getByTestId('extension-frame')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Open in window/ })).toBeNull()
  })

  it('marks a developer registration with the DEV badge and the dev version', async () => {
    const deps = fakeBundleDeps({
      devRegistration: () => ({ manifest: fakeManifest(), grantedScopes: [], grantedNetwork: [] })
    })
    renderPage({ bundleDeps: deps })
    await waitFor(() => expect(screen.getByTestId('dev-badge')).toBeInTheDocument())
    expect(screen.getByTestId('ext-page-header')).toHaveTextContent('dev')
    // No registry asset for a dev registration → the neutral tile, never a fetch.
    expect(screen.queryByTestId('extension-icon')).toBeNull()
  })
})

describe('ExtensionPageScreen states', () => {
  it('shows Downloading while caching, then the frame', async () => {
    let release: (() => void) | null = null
    const deps = fakeBundleDeps({
      bridge: fakeBridge(),
      fetchBundle: () =>
        new Promise((resolve) => {
          release = () => resolve({ bytes: new ArrayBuffer(8), contentHash: 'a'.repeat(64) })
        })
    })
    renderPage({ bundleDeps: deps })
    await waitFor(() =>
      expect(screen.getByTestId('frame-skeleton')).toHaveTextContent('Downloading BOM…')
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('BOM')
    release!()
    await waitFor(() => expect(screen.getByTestId('extension-frame')).toBeInTheDocument())
  })

  it('offers Open in Store on blocked, disabled and error cards, and Back in the header', async () => {
    const onOpenStore = vi.fn()
    const onBack = vi.fn()
    const deps = fakeBundleDeps({
      listInstalls: async () => [
        fakeInstall({ policy: { blocked: true, default_installed: false } })
      ]
    })
    renderPage({ bundleDeps: deps, onOpenStore, onBack })
    await waitFor(() => expect(screen.getByTestId('frame-blocked')).toBeInTheDocument())
    expect(screen.getByTestId('frame-blocked')).toHaveTextContent('Blocked by your team.')
    screen.getByRole('button', { name: 'Open in Store' }).click()
    expect(onOpenStore).toHaveBeenCalledTimes(1)
    screen.getByRole('button', { name: 'Back' }).click()
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('names a disabled install', async () => {
    const deps = fakeBundleDeps({ listInstalls: async () => [fakeInstall({ enabled: false })] })
    renderPage({ bundleDeps: deps, onOpenStore: () => undefined })
    await waitFor(() =>
      expect(screen.getByTestId('frame-disabled')).toHaveTextContent(
        'BOM is disabled in this project.'
      )
    )
  })
})
