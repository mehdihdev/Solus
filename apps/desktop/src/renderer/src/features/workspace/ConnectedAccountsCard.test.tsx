// Home's connected-accounts card (SOLUSDEV-241): one row per OAuth provider
// from the live registry — linked accounts with where they are used and a
// confirmed Revoke that NAMES the projects it disconnects, or a Connect that
// opens the wizard in account scope.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { reauthText, revokeDetail, scopeText, usageText } from './connectedAccounts'
import * as accountsHook from './useAccountConnections'
import * as catalogHook from '../onboarding/useIntegrationCatalog'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import type { Connection } from '../../lib/api/resources'

vi.mock('./useAccountConnections', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useAccountConnections')>()
  return { ...actual, useAccountConnections: vi.fn() }
})
vi.mock('../onboarding/useIntegrationCatalog', () => ({ useIntegrationCatalog: vi.fn() }))

const ONSHAPE: CatalogEntry = {
  id: 'onshape',
  name: 'Onshape',
  kind: 'Mechanical CAD — cloud',
  mark: 'On',
  mode: 'oauth',
  configFields: [],
  selection: { mode: 'multi', config_key: 'documents', label: 'document' },
  accessModes: null,
  hosted: null
}
const KICAD: CatalogEntry = {
  id: 'kicad',
  name: 'KiCad',
  kind: 'PCB',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export'],
  selection: null,
  accessModes: null,
  hosted: null
}

const LINKED: Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'ada@example.com',
  access: 'read',
  origin: 'home',
  needs_reauth: null,
  last_error: null,
  projects: [
    { project_id: 'p1', name: 'Rover' },
    { project_id: 'p2', name: 'Arm' }
  ],
  created_at: '',
  updated_at: ''
}

function mockAccounts(
  overrides: Partial<accountsHook.AccountConnectionsData> = {}
): accountsHook.AccountConnectionsData {
  const value: accountsHook.AccountConnectionsData = {
    status: 'ready',
    connections: [],
    refresh: vi.fn(async () => undefined),
    revoke: vi.fn(async () => true),
    ...overrides
  }
  vi.mocked(accountsHook.useAccountConnections).mockReturnValue(value)
  return value
}

beforeEach(() => {
  vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([ONSHAPE, KICAD])
})

describe('ConnectedAccountsCard', () => {
  it('lists only OAuth providers, offering Connect when nothing is linked', () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    expect(screen.getByText('Onshape')).toBeInTheDocument()
    expect(screen.queryByText('KiCad')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Onshape' })).toBeInTheDocument()
  })

  it('shows a linked account with the projects using it', () => {
    mockAccounts({ connections: [LINKED] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByText('· ada@example.com')).toBeInTheDocument()
    expect(screen.getByText(/Used in Rover and Arm/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect Onshape' })).not.toBeInTheDocument()
  })

  it('revokes only after a confirmation that names the projects', async () => {
    const accounts = mockAccounts({ connections: [LINKED] })
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('button', { name: 'Revoke Onshape' }))
    const dialog = screen.getByText(/Revoke Onshape/i).closest('div')!
    expect(
      within(dialog.parentElement!).getByText(/disconnects Onshape in Rover, Arm/)
    ).toBeTruthy()
    expect(accounts.revoke).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(accounts.revoke).toHaveBeenCalledWith('c1')
  })

  it('opens the wizard in ACCOUNT scope from Connect', async () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('button', { name: 'Connect Onshape' }))
    const dialog = screen.getByRole('dialog', { name: 'Connect Onshape' })
    // Account scope: the rail ends at the sign-in — no picking, no indexing.
    const steps = Array.from(dialog.querySelectorAll('[data-step]')).map((n) => n.textContent)
    expect(steps).toEqual(['Sign in'])
  })

  it('renders nothing while offline', () => {
    mockAccounts({ status: 'offline' })
    const { container } = render(<ConnectedAccountsCard />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('ConnectedAccountsCard — scope and re-consent (SOLUSDEV-242 / H2)', () => {
  it('states the scope of every linked account plainly', () => {
    mockAccounts({ connections: [LINKED, { ...LINKED, id: 'c2', access: 'write' }] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByText(/Used in Rover and Arm · Read only/)).toBeInTheDocument()
    expect(screen.getByText(/Used in Rover and Arm · Read and edit/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /re-authorize/i })).toBeNull()
  })

  it('says a migrated grant’s access was never recorded and offers Re-authorize without forcing it', async () => {
    mockAccounts({
      connections: [{ ...LINKED, access: null, origin: 'migrated', needs_reauth: 'access_unknown' }]
    })
    render(<ConnectedAccountsCard />)
    expect(screen.getByText(/Access level not recorded · moved from a project/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(/existing syncs keep working until then/)
    // Still listed as a working account: usage, and Revoke, are there.
    expect(screen.getByRole('button', { name: 'Revoke Onshape' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Re-authorize Onshape' }))
    const dialog = screen.getByRole('dialog', { name: 'Connect Onshape' })
    const steps = Array.from(dialog.querySelectorAll('[data-step]')).map((n) => n.textContent)
    expect(steps).toEqual(['Sign in'])
  })

  it('offers Re-authorize for a grant whose last sign-in failed', () => {
    mockAccounts({
      connections: [
        {
          ...LINKED,
          status: 'error',
          needs_reauth: 'token_error',
          last_error: { code: 'invalid_credentials', message: 'token revoked' }
        }
      ]
    })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('note')).toHaveTextContent('token revoked Re-authorize to reconnect.')
    expect(screen.getByRole('button', { name: 'Re-authorize Onshape' })).toBeInTheDocument()
  })
})

describe('copy helpers', () => {
  it('usageText counts beyond two projects', () => {
    expect(usageText({ ...LINKED, projects: [] })).toBe('Not used by any project yet')
    expect(usageText(LINKED)).toBe('Used in Rover and Arm')
    expect(
      usageText({ ...LINKED, projects: [...LINKED.projects, { project_id: 'p3', name: 'Leg' }] })
    ).toBe('Used in 3 projects')
  })

  it('scopeText and reauthText say only what is known', () => {
    expect(scopeText(LINKED)).toBe('Read only')
    expect(scopeText({ ...LINKED, access: 'write' })).toBe('Read and edit')
    expect(scopeText({ ...LINKED, access: null })).toBe('Access level not recorded')
    expect(reauthText(LINKED)).toBeNull()
    expect(reauthText({ ...LINKED, needs_reauth: 'access_unknown' })).toMatch(/never recorded/)
    expect(reauthText({ ...LINKED, status: 'error', needs_reauth: 'token_error' })).toMatch(
      /last sign-in failed/
    )
  })

  it('revokeDetail is honest about what is lost', () => {
    expect(revokeDetail('Onshape', { ...LINKED, projects: [] })).toContain('No project uses it')
    expect(revokeDetail('Onshape', LINKED)).toContain('disconnects Onshape in Rover, Arm')
  })
})
