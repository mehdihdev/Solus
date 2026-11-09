// SOLUSDEV-323: the compact starter shown to signed-out users.
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { StarterPage } from './StarterPage'

function Where(): React.JSX.Element {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderStarter(): void {
  render(
    <MemoryRouter initialEntries={['/welcome']}>
      <Routes>
        <Route path="/welcome" element={<StarterPage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('StarterPage', () => {
  it('introduces SOL with the one-system headline', () => {
    renderStarter()
    expect(screen.getByText('SOL · HELLO')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Your robot is one system/ })).toBeInTheDocument()
  })

  it('shows the four worlds it links', () => {
    renderStarter()
    for (const world of ['CODE', 'PCB', 'CAD', 'ROBOT']) {
      expect(screen.getByText(world)).toBeInTheDocument()
    }
  })

  it('Create account opens sign-up', async () => {
    renderStarter()
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/signup')
  })

  it('Sign in opens sign-in', async () => {
    renderStarter()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/login')
  })

  it('offers GitHub', () => {
    renderStarter()
    expect(screen.getByRole('button', { name: /Continue with GitHub/ })).toBeInTheDocument()
  })
})
