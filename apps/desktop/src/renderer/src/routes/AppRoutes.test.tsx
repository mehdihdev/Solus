import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppRoutes } from './AppRoutes'
import { useAuthStore } from '../store/authStore'

function renderAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>
  )
}

describe('AppRoutes guards', () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: 'unauthenticated',
      user: null,
      accessToken: null,
      onboarded: false
    })
  })

  it('shows the landing page to unauthenticated users at /', () => {
    renderAt('/')
    expect(screen.getByText('Your robot is one system.')).toBeInTheDocument()
  })

  it('redirects authenticated-but-not-onboarded users to onboarding', async () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: false })
    renderAt('/')
    // Onboarding hydrates its server-side step first (FND-08), then renders.
    expect(
      await screen.findByRole('heading', { name: 'What are you building?' })
    ).toBeInTheDocument()
  })

  it('shows the workspace shell (landing on Home) to onboarded users', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/')
    // Shell chrome renders with the honest no-project fallback (SOLUSDEV-152 —
    // no fabricated project name) and lands on the Home screen.
    expect(screen.getByText('No project')).toBeInTheDocument()
    expect(screen.getAllByText('Home').length).toBeGreaterThan(0)
  })

  it('keeps unauthenticated users on /onboarding out (sends to login)', () => {
    renderAt('/onboarding')
    expect(screen.getByText('Welcome back')).toBeInTheDocument()
  })

  it('redirects already-onboarded users away from /onboarding', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/onboarding')
    expect(screen.getAllByText('Workspace').length).toBeGreaterThan(0)
  })

  it('lets a not-yet-onboarded user reach /onboarding', async () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: false })
    renderAt('/onboarding')
    expect(
      await screen.findByRole('heading', { name: 'What are you building?' })
    ).toBeInTheDocument()
  })

  it('redirects signed-in users away from /login', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/login')
    expect(screen.getAllByText('Workspace').length).toBeGreaterThan(0)
  })

  it('serves the extension window root at /ext-window/:extensionId, which guards its own auth', () => {
    renderAt('/ext-window/bom')
    expect(screen.getByTestId('ext-window-root')).toBeInTheDocument()
    expect(
      screen.getByText('Sign in from the main Solus window to use extensions here.')
    ).toBeInTheDocument()
  })
})
