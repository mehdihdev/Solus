// SOLUSDEV-235 / EXT-13 — the #/ext-window/:extensionId root: its own auth
// guard, the persisted project, the id check, and the window-mode frame.
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { fakeBridgeDeps } from '../host/testing/fakeBridgeDeps'
import { fakeBundleDeps } from '../frame/testing/fixtures'
import { ExtensionWindowRoot, type ExtensionWindowRootProps } from './ExtensionWindowRoot'

function renderAt(path: string, props: ExtensionWindowRootProps = {}): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/ext-window/:extensionId" element={<ExtensionWindowRoot {...props} />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'a@b.dev' },
    accessToken: null,
    onboarded: true
  })
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover' }, linked: true })
})

describe('ExtensionWindowRoot', () => {
  it('mounts the window-mode frame for the open project with the manifest title', async () => {
    renderAt('/ext-window/bom', { bundleDeps: fakeBundleDeps(), bridgeDeps: fakeBridgeDeps() })
    await waitFor(() => expect(screen.getByTestId('extension-frame')).toBeInTheDocument())
    const frame = screen.getByTestId('extension-frame')
    expect(frame.getAttribute('src')).toBe('solus-ext://bom/1.2.0/window.html')
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('BOM window')
    expect(screen.queryByTestId('dev-badge')).toBeNull()
  })

  it('tells an unauthenticated window to sign in from the main window, fetching nothing', () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    const deps = fakeBundleDeps()
    renderAt('/ext-window/bom', { bundleDeps: deps })
    expect(
      screen.getByText('Sign in from the main Solus window to use extensions here.')
    ).toBeInTheDocument()
    expect(deps.listInstalls).not.toHaveBeenCalled()
  })

  it('waits on a loading session', () => {
    useAuthStore.setState({ status: 'loading' })
    renderAt('/ext-window/bom')
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
  })

  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    renderAt('/ext-window/bom', { bundleDeps: fakeBundleDeps() })
    expect(
      screen.getByText('Open a project in the main Solus window to use bom here.')
    ).toBeInTheDocument()
  })

  it('refuses an id that is not an extension slug', () => {
    const deps = fakeBundleDeps()
    renderAt('/ext-window/__proto__', { bundleDeps: deps })
    expect(screen.getByText(/does not recognise/)).toBeInTheDocument()
    expect(deps.listInstalls).not.toHaveBeenCalled()
  })
})
