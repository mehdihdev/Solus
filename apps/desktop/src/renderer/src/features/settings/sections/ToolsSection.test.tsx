import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToolsSection } from './ToolsSection'
import { integrationLogo } from '../../onboarding/integrationLogos'
import type { Connection } from '../../../lib/api/resources'

function conn(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    provider: 'github',
    status: 'connected',
    account_login: 'maya',
    access: 'read',
    needs_reauth: null,
    last_error: null,
    health: 'healthy',
    projects: [{ project_id: 'p1', name: 'Rover' } as Connection['projects'][number]],
    created_at: '',
    updated_at: '',
    ...overrides
  }
}

describe('ToolsSection', () => {
  it('lists each linked account with its real status, not a catalog', () => {
    render(
      <ToolsSection
        status="ready"
        connections={[
          conn(),
          conn({ id: 'c2', provider: 'onshape', health: 'token_expired', account_login: 'mk' }),
          conn({ id: 'c3', provider: 'kicad', status: 'revoked' })
        ]}
        onManage={vi.fn()}
      />
    )
    expect(screen.getByText('GitHub')).toBeInTheDocument()
    expect(screen.getByText(/@maya · used in 1 project$/)).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('Reconnect')).toBeInTheDocument()
    // Revoked grants are gone, not "disconnected" rows.
    expect(screen.queryByText('KiCad')).toBeNull()
    expect(screen.queryByText('AVAILABLE')).toBeNull()
  })

  it('sends management to Home › Connected accounts', async () => {
    const onManage = vi.fn()
    render(<ToolsSection status="ready" connections={[conn()]} onManage={onManage} />)
    await userEvent.click(screen.getByRole('button', { name: /Manage connected accounts/ }))
    expect(onManage).toHaveBeenCalled()
  })

  it('offers to connect a first tool when none are linked', async () => {
    const onManage = vi.fn()
    render(<ToolsSection status="ready" connections={[]} onManage={onManage} />)
    expect(screen.getByText(/No tool accounts are connected yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Connect a tool' }))
    expect(onManage).toHaveBeenCalled()
  })

  it('draws the same brand logos as Home › Connected accounts', () => {
    const { container } = render(
      <ToolsSection
        status="ready"
        connections={[conn(), conn({ id: 'c2', provider: 'onshape' })]}
        onManage={vi.fn()}
      />
    )
    const logos = [...container.querySelectorAll('img')].map((img) => img.getAttribute('src'))
    expect(logos).toEqual([integrationLogo('github'), integrationLogo('onshape')])
    expect(logos[0]).toBeTruthy()
  })

  it('carries no note about the Onshape panel pairing', () => {
    render(<ToolsSection status="ready" connections={[]} onManage={vi.fn()} />)
    expect(screen.queryByText(/Onshape panel/)).toBeNull()
  })

  it('shows a loading line until the accounts are read', () => {
    render(<ToolsSection status="loading" connections={[]} onManage={vi.fn()} />)
    expect(screen.getByText(/Loading connected accounts/)).toBeInTheDocument()
  })
})
