// Home's connected-accounts card (SOLUSDEV-241): one row per OAuth provider
// from the live registry — linked accounts with where they are used and a
// confirmed Revoke that NAMES the projects it disconnects, or a Connect that
// opens the wizard in account scope.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { ACCOUNT_DOMAINS, accountDomain, emptyDomainText } from './accountDomains'
import {
  healthLabel,
  legacyText,
  moveDetail,
  quotaNote,
  quotaText,
  reauthText,
  revokeDetail,
  scopeText,
  usageText
} from './connectedAccounts'
import * as accountsHook from './useAccountConnections'
import * as catalogHook from '../onboarding/useIntegrationCatalog'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import type { Connection, LegacyConnection } from '../../lib/api/resources'

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
  needs_reauth: null,
  last_error: null,
  health: 'healthy',
  projects: [
    { project_id: 'p1', name: 'Rover' },
    { project_id: 'p2', name: 'Arm' }
  ],
  created_at: '',
  updated_at: ''
}

const LEGACY: LegacyConnection = {
  provider: 'onshape',
  account_login: 'ada-legacy',
  projects: [{ project_id: 'p1', name: 'Rover' }],
  source_ids: ['s-legacy'],
  claimable_connection_id: null
}

function mockAccounts(
  overrides: Partial<accountsHook.AccountConnectionsData> = {}
): accountsHook.AccountConnectionsData {
  const value: accountsHook.AccountConnectionsData = {
    status: 'ready',
    connections: [],
    legacy: [],
    refresh: vi.fn(async () => undefined),
    revoke: vi.fn(async () => true),
    move: vi.fn(async () => true),
    ...overrides
  }
  vi.mocked(accountsHook.useAccountConnections).mockReturnValue(value)
  return value
}

beforeEach(() => {
  vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([ONSHAPE, KICAD])
})

describe('ConnectedAccountsCard', () => {
  it('offers Connect for an OAuth provider when nothing is linked', async () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    expect(screen.getByText('Onshape')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Onshape' })).toBeInTheDocument()
    // A file-export tool is listed too (under its own domain), but has no account to connect.
    await userEvent.click(screen.getByRole('tab', { name: 'Electrical' }))
    expect(screen.getByText('KiCad')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect KiCad' })).toBeNull()
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

  it('lists a legacy project-scoped grant as "sign in once to move it", unmoved and honest', async () => {
    mockAccounts({ legacy: [LEGACY] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByText(/Onshape/)).toBeInTheDocument()
    expect(screen.getByText('Connected in a project, not yet on your account')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(
      'Connected in Rover before account-level connections. Sign in once to move it to your account — Rover keeps syncing until then.'
    )
    // Not a usable grant: no Revoke, no duplicate Connect.
    expect(screen.queryByRole('button', { name: 'Revoke Onshape' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Connect Onshape' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in to move Onshape' }))
    const dialog = screen.getByRole('dialog', { name: 'Connect Onshape' })
    const steps = Array.from(dialog.querySelectorAll('[data-step]')).map((n) => n.textContent)
    expect(steps).toEqual(['Sign in'])
  })

  it('shows a linked account and a still-legacy grant for the same provider side by side', () => {
    mockAccounts({ connections: [LINKED], legacy: [LEGACY] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('button', { name: 'Revoke Onshape' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in to move Onshape' })).toBeInTheDocument()
  })

  it('offers the move as a confirmed action naming the project and the grant once the account is proved', async () => {
    const accounts = mockAccounts({
      connections: [LINKED],
      legacy: [{ ...LEGACY, claimable_connection_id: LINKED.id }]
    })
    render(<ConnectedAccountsCard />)
    expect(screen.queryByRole('button', { name: 'Sign in to move Onshape' })).toBeNull()
    expect(screen.getByRole('note')).toHaveTextContent('Your linked account matches')
    await userEvent.click(screen.getByRole('button', { name: 'Move Onshape to your account' }))
    // Nothing moves before the confirmation; the dialog says exactly what happens.
    expect(accounts.move).not.toHaveBeenCalled()
    expect(
      screen.getByText(/Rover will use your linked Onshape account \(read only access\)/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/own Onshape token — and any add-on grant on it — is removed/)
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    expect(accounts.move).toHaveBeenCalledWith(
      expect.objectContaining({ source_ids: ['s-legacy'] }),
      expect.objectContaining({ id: 'c1', access: 'read' })
    )
  })

  it('never offers a blanket Move when the proving grant cannot be named', () => {
    // The id says claimable, but the list has no such grant (stale refresh):
    // no confirmation could state the scope, so no move is offered.
    mockAccounts({ connections: [], legacy: [{ ...LEGACY, claimable_connection_id: 'c-gone' }] })
    render(<ConnectedAccountsCard />)
    expect(screen.queryByRole('button', { name: 'Move Onshape to your account' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Sign in to move Onshape' })).toBeInTheDocument()
  })

  it('a write grant is named as read and edit in the confirmation before anything moves', async () => {
    const write = { ...LINKED, access: 'write' as const }
    const accounts = mockAccounts({
      connections: [write],
      legacy: [{ ...LEGACY, claimable_connection_id: write.id }]
    })
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('button', { name: 'Move Onshape to your account' }))
    expect(screen.getByText(/\(read and edit access\)/)).toBeInTheDocument()
    expect(accounts.move).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    expect(accounts.move).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ access: 'write' })
    )
  })

  it('keeps the move dialog open and says so when the move fails', async () => {
    const accounts = mockAccounts({
      connections: [LINKED],
      legacy: [{ ...LEGACY, claimable_connection_id: LINKED.id }]
    })
    vi.mocked(accounts.move).mockResolvedValue(false)
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('button', { name: 'Move Onshape to your account' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    expect(screen.getByText(/Couldn't move this Onshape connection/)).toBeInTheDocument()
  })

  it('lists every catalog tool under its domain; a per-project tool attaches from the open project', async () => {
    mockAccounts()
    const onOpenSources = vi.fn()
    render(
      <ConnectedAccountsCard
        currentProject={{ id: 'p1', name: 'Rover', teamId: 't1' }}
        onOpenSources={onOpenSources}
      />
    )
    expect(screen.getByText('Onshape')).toBeInTheDocument()
    expect(screen.queryByText('KiCad')).toBeNull()
    await userEvent.click(screen.getByRole('tab', { name: 'Electrical' }))
    expect(screen.queryByText('Onshape')).toBeNull()
    expect(screen.getByText('KiCad')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect KiCad' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Attach KiCad in Rover' }))
    expect(onOpenSources).toHaveBeenCalled()
  })

  it('without an open project a per-project tool says so and offers no button', async () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('tab', { name: 'Electrical' }))
    expect(
      screen.getByText(/open a project to attach it from its Sources page/)
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /attach kicad/i })).toBeNull()
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
    expect(screen.getByRole('note')).toHaveTextContent('token revoked. Re-authorize to reconnect.')
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
    expect(legacyText(LEGACY)).toMatch(/Connected in Rover before/)
    expect(legacyText({ ...LEGACY, projects: [] })).toMatch(/Connected in a project/)
    expect(
      legacyText({ ...LEGACY, projects: [...LEGACY.projects, { project_id: 'p2', name: 'Arm' }] })
    ).toMatch(/Rover and Arm.*those projects keep syncing/)
    expect(legacyText({ ...LEGACY, claimable_connection_id: 'c1' })).toMatch(
      /linked account matches/
    )
    expect(moveDetail('Onshape', LEGACY, LINKED)).toMatch(
      /Rover will use your linked Onshape account \(read only access\)/
    )
    expect(moveDetail('Onshape', LEGACY, { ...LINKED, access: 'write' })).toMatch(
      /\(read and edit access\)/
    )
    expect(
      moveDetail(
        'Onshape',
        { ...LEGACY, projects: [...LEGACY.projects, { project_id: 'p2', name: 'Arm' }] },
        LINKED
      )
    ).toMatch(/Rover and Arm will use.*Each project's own Onshape token/)
    expect(reauthText({ ...LINKED, status: 'error', needs_reauth: 'token_error' })).toMatch(
      /last sign-in failed/
    )
  })

  it('revokeDetail is honest about what is lost', () => {
    expect(revokeDetail('Onshape', { ...LINKED, projects: [] })).toContain('No project uses it')
    expect(revokeDetail('Onshape', LINKED)).toContain('disconnects Onshape in Rover, Arm')
  })
})

describe('ConnectedAccountsCard — health and quota (SOLUSDEV-244 / H4)', () => {
  it('a healthy metered account states its estimated position, quietly', () => {
    mockAccounts({
      connections: [
        { ...LINKED, quota: { status: 'ok', used: 120, allowance: 1800, estimated: true } }
      ]
    })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('status')).toHaveTextContent('Healthy')
    expect(
      screen.getByText('At least 120 of 1,800 Onshape calls this year (estimate)')
    ).toBeInTheDocument()
    expect(screen.queryByTestId('quota-note')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Re-authorize Onshape' })).toBeNull()
  })

  it('an unmetered account says nothing about quota', () => {
    mockAccounts({ connections: [LINKED] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('status')).toHaveTextContent('Healthy')
    expect(screen.queryByText(/calls this year/)).toBeNull()
    expect(screen.queryByTestId('quota-bar')).toBeNull()
  })

  it('flags an account at 80% BEFORE the wall and says what degrades', () => {
    mockAccounts({
      connections: [
        {
          ...LINKED,
          health: 'degraded',
          quota: { status: 'degraded', used: 1440, allowance: 1800, estimated: true }
        }
      ]
    })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('status')).toHaveTextContent('Degraded')
    expect(screen.getByText(/At least 1,440 of 1,800 .* \(estimate\)/)).toBeInTheDocument()
    const note = screen.getByTestId('quota-note')
    expect(note).toHaveTextContent("Approaching Onshape's call limit")
    expect(note).toHaveTextContent('Automatic syncs and SOL')
    expect(note).toHaveTextContent('your own Sync now still reaches Onshape')
    expect(note).toHaveTextContent('cache-only reads and starts no new syncs')
    expect(screen.getByTestId('quota-bar')).toHaveStyle({ width: '80%' })
    expect(screen.queryByRole('button', { name: 'Re-authorize Onshape' })).toBeNull()
  })

  it('at the wall it explains cache-only mode rather than showing an error', () => {
    mockAccounts({
      connections: [
        {
          ...LINKED,
          health: 'degraded',
          quota: { status: 'exhausted', used: 1800, allowance: 1800, estimated: true }
        }
      ]
    })
    render(<ConnectedAccountsCard />)
    const note = screen.getByTestId('quota-note')
    expect(note).toHaveTextContent('cache-only mode')
    expect(note).toHaveTextContent('documents already synced stay readable')
    expect(note).toHaveTextContent('not an error')
    // No error framing anywhere: no sign-in prompt, no failure wording.
    expect(screen.queryByText(/sign-in failed|rejected|re-authorize/i)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Re-authorize Onshape' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Revoke Onshape' })).toBeInTheDocument()
  })

  it('an expired token offers reconnect in place even when the grant row is still connected', async () => {
    const accounts = mockAccounts({ connections: [{ ...LINKED, health: 'token_expired' }] })
    render(<ConnectedAccountsCard />)
    expect(screen.getByRole('status')).toHaveTextContent('Token expired')
    expect(screen.getByRole('note')).toHaveTextContent('rejected this account')
    await userEvent.click(screen.getByRole('button', { name: 'Re-authorize Onshape' }))
    expect(accounts.refresh).not.toHaveBeenCalled() // the wizard opens; nothing moves yet
  })

  it('copy helpers are honest about what is an estimate and what is unknown', () => {
    expect(healthLabel(LINKED)).toBe('Healthy')
    expect(quotaText(LINKED, 'Onshape')).toBeNull()
    expect(quotaNote(LINKED, 'Onshape')).toBeNull()
    const degraded = {
      ...LINKED,
      quota: { status: 'degraded' as const, used: 1440, allowance: 1800, estimated: true }
    }
    expect(quotaText(degraded, 'Onshape')).toMatch(/\(estimate\)$/)
    expect(quotaText(degraded, 'Onshape')).not.toMatch(/remaining|left/)
  })
})

describe('ConnectedAccountsCard — domain tabs (SOLUSDEV-244)', () => {
  const GITHUB: CatalogEntry = {
    id: 'github',
    name: 'GitHub',
    kind: 'Code',
    mark: 'GH',
    mode: 'oauth',
    configFields: ['repo', 'branch'],
    selection: null,
    accessModes: null,
    hosted: null
  }
  const FUSION: CatalogEntry = {
    id: 'fusion',
    name: 'Fusion',
    kind: 'Local tool — companion bridge',
    mark: 'Fu',
    mode: 'local-bridge',
    configFields: [],
    selection: null,
    accessModes: null,
    hosted: null
  }

  it('shows the four domains in order, Mechanical selected first', () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['Mechanical', 'Electrical', 'Simulation', 'Software'])
    expect(screen.getByRole('tab', { name: 'Mechanical' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Software' })).toHaveAttribute('aria-selected', 'false')
  })

  it('groups tools by domain and keeps account tools ahead of per-project ones', async () => {
    vi.mocked(catalogHook.useIntegrationCatalog).mockReturnValue([FUSION, KICAD, GITHUB, ONSHAPE])
    mockAccounts()
    render(<ConnectedAccountsCard />)
    const rows = (): string[] =>
      screen.getAllByText(/^(Onshape|KiCad|GitHub|Fusion)$/).map((n) => n.textContent ?? '')
    expect(rows()).toEqual(['Onshape', 'Fusion'])
    await userEvent.click(screen.getByRole('tab', { name: 'Software' }))
    expect(rows()).toEqual(['GitHub'])
    expect(screen.getByRole('tab', { name: 'Software' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Connect GitHub' })).toBeInTheDocument()
  })

  it('an empty domain says what will land there instead of an empty box', async () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    await userEvent.click(screen.getByRole('tab', { name: 'Simulation' }))
    expect(screen.getByRole('tabpanel')).toHaveTextContent(/MuJoCo and Isaac Sim/)
    expect(screen.getAllByRole('tab')).toHaveLength(4) // the tabs remain
    expect(screen.queryByRole('button', { name: /connect|attach|revoke/i })).toBeNull()
  })

  it('no longer points at the Sources page under the card', () => {
    mockAccounts()
    render(<ConnectedAccountsCard />)
    expect(screen.queryByText(/Link an account once/)).toBeNull()
  })

  it('classifies known providers and falls back to Software for an unknown one', () => {
    expect(ACCOUNT_DOMAINS).toEqual(['mechanical', 'electrical', 'simulation', 'software'])
    expect(accountDomain({ id: 'onshape' })).toBe('mechanical')
    expect(accountDomain({ id: 'fusion' })).toBe('mechanical')
    expect(accountDomain({ id: 'kicad' })).toBe('electrical')
    expect(accountDomain({ id: 'altium' })).toBe('electrical')
    expect(accountDomain({ id: 'mujoco' })).toBe('simulation')
    expect(accountDomain({ id: 'github' })).toBe('software')
    expect(accountDomain({ id: 'gitlab' })).toBe('software')
    expect(accountDomain({ id: 'brand-new-tool' })).toBe('software')
    expect(emptyDomainText('simulation')).toMatch(/MuJoCo/)
    expect(emptyDomainText('electrical')).toMatch(/No electrical tools/)
  })
})
