// SOLUSDEV-323: the compact signed-out window — starter, sign in, create
// account — one persistent shell whose orb and size ease between screens.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AuthShell } from './AuthShell'
import { StarterPage } from './StarterPage'
import { LoginPage } from './LoginPage'
import { SignupPage } from './SignupPage'
import { useAuthStore } from '../../store/authStore'

function Where(): React.JSX.Element {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AuthShell />}>
          <Route path="/welcome" element={<StarterPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
        </Route>
        <Route path="/" element={<Where />} />
      </Routes>
    </MemoryRouter>
  )
}

let setWindowSize: ReturnType<typeof vi.fn>

describe('AuthShell', () => {
  beforeEach(() => {
    setWindowSize = vi.fn().mockResolvedValue(true)
    ;(window as { solus?: unknown }).solus = { setWindowSize, platform: 'darwin' }
    useAuthStore.setState({ status: 'unauthenticated', user: null, accessToken: null })
  })
  afterEach(() => {
    delete (window as { solus?: unknown }).solus
  })

  it('asks for the compact starter size at /welcome', () => {
    renderAt('/welcome')
    expect(setWindowSize).toHaveBeenCalledWith(expect.objectContaining({ size: 'starter' }))
    expect(screen.getByTestId('auth-orb')).toHaveAttribute('data-state', 'big')
  })

  it('keeps one orb and grows to the auth size when a form opens', async () => {
    renderAt('/welcome')
    const orb = screen.getByTestId('auth-orb')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByTestId('auth-orb')).toBe(orb)
    expect(orb).toHaveAttribute('data-state', 'small')
    expect(setWindowSize).toHaveBeenLastCalledWith(expect.objectContaining({ size: 'auth' }))
  })

  it('goes back to the starter from a form', async () => {
    renderAt('/login')
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument()
  })

  it('grows the window to full before leaving once signed in', async () => {
    renderAt('/signup')
    act(() => {
      useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    })
    expect(screen.getByTestId('auth-shell')).toHaveAttribute('data-leaving', 'true')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/'))
    expect(setWindowSize).toHaveBeenLastCalledWith(expect.objectContaining({ size: 'full' }))
  })

  it('sends an already signed-in user straight on', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    renderAt('/login')
    expect(screen.getByTestId('where')).toHaveTextContent('/')
  })
})
