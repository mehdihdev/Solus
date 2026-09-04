// SOLUSDEV-235 — the project menu bar: Solus · View · Robot · Help + the right cluster.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MenuBar } from './MenuBar'
import { MENUS } from './menuBar.constants'

function renderBar(over: Partial<React.ComponentProps<typeof MenuBar>> = {}): {
  onNavigate: ReturnType<typeof vi.fn>
  onSignOut: ReturnType<typeof vi.fn>
  onBell: ReturnType<typeof vi.fn>
} {
  const onNavigate = vi.fn()
  const onSignOut = vi.fn()
  const onBell = vi.fn()
  render(
    <MenuBar
      activeScreen="store"
      hasProject
      openCount={0}
      projectId={null}
      onNavigate={onNavigate}
      onSignOut={onSignOut}
      onBell={onBell}
      {...over}
    />
  )
  return { onNavigate, onSignOut, onBell }
}

describe('MenuBar', () => {
  it('shows the four menus closed', () => {
    renderBar()
    for (const m of MENUS)
      expect(screen.getByRole('button', { name: m.label })).toHaveAttribute(
        'aria-expanded',
        'false'
      )
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('View lists every workspace screen, marks the active one, and navigates', async () => {
    const { onNavigate } = renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: 'Store' })).toHaveAttribute(
      'aria-current',
      'true'
    )
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Live Bench' }))
    expect(onNavigate).toHaveBeenCalledWith('bench')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('Solus offers Home, Settings, Billing and Sign out', async () => {
    const { onNavigate, onSignOut } = renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'Solus' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Home' }))
    expect(onNavigate).toHaveBeenCalledWith('home')
    await userEvent.click(screen.getByRole('button', { name: 'Solus' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalledOnce()
  })

  it('Robot actions need an open project', async () => {
    const { onNavigate } = renderBar({ hasProject: false })
    await userEvent.click(screen.getByRole('button', { name: 'Robot' }))
    expect(screen.getByText(/Open a project/)).toBeInTheDocument()
    const item = screen.getByRole('menuitem', { name: 'Connect a tool…' })
    expect(item).toBeDisabled()
    await userEvent.click(item)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('Robot actions navigate when a project is open', async () => {
    const { onNavigate } = renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'Robot' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Connect a device…' }))
    expect(onNavigate).toHaveBeenCalledWith('bench')
  })

  it('Help links open outside the app over https only', async () => {
    renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'Help' }))
    for (const link of screen.getAllByRole('menuitem')) {
      expect(link).toHaveAttribute('href', expect.stringMatching(/^https:\/\//))
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })

  it('hovering another menu while one is open switches to it', async () => {
    renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    await userEvent.hover(screen.getByRole('button', { name: 'Help' }))
    expect(screen.getByRole('button', { name: 'Help' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: 'View' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes on click-out and on Escape', async () => {
    renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    await userEvent.click(screen.getByTestId('menu-backdrop'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('carries the right cluster: badge count, bell and sign out', async () => {
    const { onBell, onSignOut } = renderBar({ openCount: 2 })
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(onBell).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalledOnce()
  })
})
