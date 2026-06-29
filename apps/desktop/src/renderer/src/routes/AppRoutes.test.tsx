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

  it('redirects authenticated-but-not-onboarded users to onboarding', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: false })
    renderAt('/')
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
  })

  it('shows the workspace home to onboarded users', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/')
    expect(screen.getByRole('heading', { name: 'Your context model is ready' })).toBeInTheDocument()
  })

  it('keeps unauthenticated users on /onboarding out (sends to login)', () => {
    renderAt('/onboarding')
    expect(screen.getByText('Welcome back')).toBeInTheDocument()
  })

  it('redirects already-onboarded users away from /onboarding', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/onboarding')
    expect(screen.getByRole('heading', { name: 'Your context model is ready' })).toBeInTheDocument()
  })

  it('lets a not-yet-onboarded user reach /onboarding', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: false })
    renderAt('/onboarding')
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
  })

  it('redirects signed-in users away from /login', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
    renderAt('/login')
    expect(screen.getByRole('heading', { name: 'Your context model is ready' })).toBeInTheDocument()
  })
})
