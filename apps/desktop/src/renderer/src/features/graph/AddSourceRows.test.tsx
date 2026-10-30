// The Add modal's left column: accounts lead with the provider logo (letter mark when none is
// bundled) and the login — never an id — plus the .solus and Hardware rows.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Connection } from '../../lib/api/resources'
import { AddSourceRows, accountUsable, sameTarget } from './AddSourceRows'
import type { CatalogSnapshot } from './serviceCatalog'

const account = (override: Partial<Connection>): Connection => ({
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'builder',
  access: 'read',
  last_error: null,
  needs_reauth: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: '',
  ...override
})

function mount(
  accounts: Connection[],
  over: Partial<CatalogSnapshot> = {}
): { onSelect: ReturnType<typeof vi.fn>; onRefresh: ReturnType<typeof vi.fn> } {
  const onSelect = vi.fn()
  const onRefresh = vi.fn()
  render(
    <AddSourceRows
      state={{ status: 'ready', accounts, error: null, documents: {}, ...over }}
      selected={{ kind: 'account', id: 'c1' }}
      onSelect={onSelect}
      onRefresh={onRefresh}
    />
  )
  return { onSelect, onRefresh }
}

describe('AddSourceRows', () => {
  it('shows the bundled logo, the login and the real document count for a known provider', () => {
    mount([account({})], {
      documents: {
        c1: { status: 'ready', items: [{ id: 'd1', name: 'A' }], fetchedAt: 'now', error: null }
      }
    })
    const row = screen.getByRole('tab', { name: 'onshape · builder' })
    expect(row).toHaveAttribute('aria-selected', 'true')
    expect(row).toHaveTextContent('builder')
    expect(row).toHaveTextContent('1 document')
    expect(row).not.toHaveTextContent('c1')
    expect(row.querySelector('img')).toHaveAttribute('alt', '')
  })

  it('falls back to a letter mark and the provider name when nothing else is known', () => {
    mount([
      account({ id: 'c2', provider: 'github', account_login: null }),
      account({ id: 'c3', provider: 'futurecad', account_login: 'maker' })
    ])
    expect(screen.getByRole('tab', { name: 'github · github' })).toHaveTextContent('github')
    const unknown = screen.getByRole('tab', { name: 'futurecad · maker' })
    expect(unknown.querySelector('img')).toBeNull()
    expect(unknown).toHaveTextContent('F')
    expect(unknown).toBeDisabled() // not a workspace service
  })

  it('keeps a non-connected account disabled and always offers .solus and Hardware', () => {
    const { onSelect, onRefresh } = mount([account({ status: 'revoked' })])
    expect(screen.getByRole('tab', { name: 'onshape · builder' })).toBeDisabled()
    fireEvent.click(screen.getByRole('tab', { name: '.solus' }))
    expect(onSelect).toHaveBeenLastCalledWith({ kind: 'solus' })
    fireEvent.click(screen.getByRole('tab', { name: 'Hardware' }))
    expect(onSelect).toHaveBeenLastCalledWith({ kind: 'hardware' })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }))
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('is honest while loading and when nothing is connected', () => {
    mount([], { status: 'loading' })
    expect(screen.getByRole('status')).toHaveTextContent('Loading accounts…')
    mount([])
    expect(screen.getByText('Connect an account in Home to add its documents.')).toBeInTheDocument()
  })

  it('helpers: sameTarget and accountUsable', () => {
    expect(sameTarget({ kind: 'solus' }, { kind: 'solus' })).toBe(true)
    expect(sameTarget({ kind: 'account', id: 'a' }, { kind: 'account', id: 'b' })).toBe(false)
    expect(accountUsable(account({}))).toBe(true)
    expect(accountUsable(account({ provider: 'kicad' }))).toBe(false)
  })
})
