// SOLUSDEV-250 P1: an account row leads with the provider logo (letter mark
// when none is bundled) and names the account by its login — never an id.
import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { api } from '../../lib/api/client'
import type { Connection } from '../../lib/api/resources'
import { ServiceCatalog, type CatalogSnapshot } from './serviceCatalog'
import { ServiceAccountPanel } from './ServiceAccountPanel'
import type { useServiceAttachments } from './useServiceAttachments'

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
const project = {
  state: { busyId: null, sources: [], error: null },
  session: { load: vi.fn(), select: vi.fn() }
} as unknown as ReturnType<typeof useServiceAttachments>
const mount = (accounts: Connection[]): void => {
  const state: CatalogSnapshot = { status: 'ready', accounts, error: null, documents: {} }
  render(
    <ServiceAccountPanel
      catalog={new ServiceCatalog(api)}
      state={state}
      project={project}
      expanded={null}
      onExpand={vi.fn()}
    />
  )
}

it('shows the bundled logo and the login for a known provider', () => {
  mount([account({})])
  const row = screen.getByRole('button', { name: 'onshape · builder' })
  expect(row).toHaveTextContent('builder')
  expect(row).not.toHaveTextContent('c1')
  expect(row.querySelector('img')).toHaveAttribute('alt', '')
})

it('falls back to a letter mark and the provider name when nothing else is known', () => {
  mount([account({ id: 'c2', provider: 'github', account_login: null })])
  const row = screen.getByRole('button', { name: 'github · github' })
  expect(row).toHaveTextContent('github')
  expect(row).not.toHaveTextContent('c2')
  // The github svg is bundled; an unknown provider renders its initial instead.
  mount([account({ id: 'c3', provider: 'futurecad', account_login: 'maker' })])
  const unknown = screen.getByRole('button', { name: 'futurecad · maker' })
  expect(unknown.querySelector('img')).toBeNull()
  expect(unknown).toHaveTextContent('F')
})

it('keeps a non-connected account disabled', () => {
  mount([account({ status: 'revoked' })])
  expect(screen.getByRole('button', { name: 'onshape · builder' })).toBeDisabled()
})
