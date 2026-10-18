// The connect wizard (SOLUSDEV-165): one modal that walks any connector's
// declared shape — dynamic step rail, SOL-mode instructions, and a generic
// action area (button / grant choice / picker / details form / file pick /
// progress / done / error). Assertions avoid provider ids on purpose.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConnectWizardModal, isSecretField } from './ConnectWizardModal'
import type { CatalogEntry } from './integrationCatalog'
import type { ConnectionState } from './onboardingStore'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as teamGithub from '../../lib/api/resources.teamGithub'
import { useTeamPick } from './useConnectWizard'

vi.mock('../../lib/api/resources.teamGithub', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources.teamGithub')>()
  return { ...actual, getTeamInstallation: vi.fn(), listTeamGithubRepos: vi.fn() }
})

const OAUTH_PICK: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'GH',
  mode: 'oauth',
  configFields: ['repo', 'branch'],
  selection: { mode: 'single', config_key: 'repo', label: 'repository' },
  accessModes: null,
  hosted: null
}

const OAUTH_FIELDS: CatalogEntry = {
  id: 'someFutureCad',
  name: 'FutureCAD',
  kind: 'CAD',
  mark: 'FC',
  mode: 'oauth',
  configFields: ['document_id', 'license_key'],
  selection: null,
  accessModes: null,
  hosted: null
}

const OAUTH_ACCESS: CatalogEntry = {
  ...OAUTH_FIELDS,
  accessModes: {
    default: 'read',
    modes: [
      { id: 'read', label: 'Read-only', description: 'Read models', scopes: [] },
      { id: 'write', label: 'Read and edit', description: 'Read and change models', scopes: [] }
    ]
  }
}

const EXPORT_FILE: CatalogEntry = {
  id: 'kicad',
  name: 'KiCad',
  kind: 'PCB',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export', 'board'],
  selection: null,
  accessModes: null,
  hosted: null
}

const SINGLE_EXPORT_FILE: CatalogEntry = {
  ...EXPORT_FILE,
  id: 'altium',
  name: 'Altium',
  mark: 'Al',
  configFields: ['export']
}

const KICAD_HINT = /Schematics \(\.kicad_sch\) can't be read directly yet/

interface Handlers {
  onBegin: ReturnType<typeof vi.fn>
  onPickFiles: ReturnType<typeof vi.fn>
  onSelect: ReturnType<typeof vi.fn>
  onSubmitConfig: ReturnType<typeof vi.fn>
  onChooseAccess: ReturnType<typeof vi.fn>
  onClose: ReturnType<typeof vi.fn>
}

function renderWizard(entry: CatalogEntry, state?: ConnectionState): Handlers {
  const handlers: Handlers = {
    onBegin: vi.fn(),
    onPickFiles: vi.fn(),
    onSelect: vi.fn(),
    onSubmitConfig: vi.fn(),
    onChooseAccess: vi.fn(),
    onClose: vi.fn()
  }
  render(<ConnectWizardModal entry={entry} state={state} {...handlers} />)
  return handlers
}

beforeEach(() => {
  useSettingsStore.getState().setSolMode('Guide')
})

describe('ConnectWizardModal', () => {
  registerWizardPresentationTests()

  registerWizardInputsTests()

  registerWizardRecoveryTests()

  registerWizardModesTests()
})

// Connector-ingested content (repo/document names, registry copy) is untrusted
// input to the UI (CLAUDE.md §7). This is the standing regression guard that it
// renders as literal TEXT — a markup-named repository must never become markup.
// Legitimate <img>s exist (bundled logos), so the guard is payload-specific:
// no element carries the payload's src or an onerror handler.
describe('untrusted content rendering', () => {
  const PAYLOAD = '<img src=x onerror="alert(1)">'

  const assertInert = (container: HTMLElement): void => {
    expect(container.querySelector('img[src="x"]')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
  }

  it('renders a markup-named selectable item as literal text, creating no element', () => {
    const { container } = render(
      <ConnectWizardModal
        entry={OAUTH_PICK}
        state={{
          phase: 'busy',
          stage: 'configure',
          selectable: [
            { id: 'a', name: PAYLOAD },
            { id: 'b', name: 'safe' }
          ],
          selectionMode: 'multi'
        }}
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(PAYLOAD)).toBeTruthy()
    assertInert(container)
  })

  it('renders markup in access-mode labels and descriptions as literal text', () => {
    const entry: CatalogEntry = {
      ...OAUTH_ACCESS,
      accessModes: {
        default: 'read',
        modes: [
          { id: 'read', label: PAYLOAD, description: `desc ${PAYLOAD}`, scopes: [] },
          { id: 'write', label: 'safe', description: 'safe desc', scopes: [] }
        ]
      }
    }
    const { container } = render(
      <ConnectWizardModal
        entry={entry}
        state={{ phase: 'busy', stage: 'access', accessModes: entry.accessModes! }}
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(`desc ${PAYLOAD}`)).toBeTruthy()
    assertInert(container)
  })

  it('renders a markup-carrying live error verbatim as text', () => {
    const { container } = render(
      <ConnectWizardModal
        entry={OAUTH_PICK}
        state={{ phase: 'error', error: `failed: ${PAYLOAD}` }}
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(`failed: ${PAYLOAD}`)).toBeTruthy()
    assertInert(container)
  })
})

describe('isSecretField', () => {
  it('masks keys, tokens, licenses and passwords; leaves ids alone', () => {
    for (const field of ['license_key', 'api_token', 'client_secret', 'password']) {
      expect(isSecretField(field)).toBe(true)
    }
    for (const field of ['document_id', 'repo', 'branch', 'workspace_id']) {
      expect(isSecretField(field)).toBe(false)
    }
  })
})

function registerWizardPresentationTests(): void {
  it('renders the rail derived from the connector shape, first step current', () => {
    renderWizard(OAUTH_PICK)
    const rail = screen.getByLabelText('Connect steps')
    const steps = Array.from(rail.querySelectorAll('[data-step]')).map((el) => el.textContent)
    expect(steps).toEqual(['Sign in', 'Pick repositories', 'Build graph'])
    expect(rail.querySelector('[aria-current="step"]')?.textContent).toBe('Sign in')
  })

  it('draws the Solus logo, not a letter, at the Solus end of the link (SOLUSDEV-253)', () => {
    renderWizard(OAUTH_PICK)
    const solusEnd = document.querySelector('[aria-label="Solus"]')
    expect(solusEnd?.querySelector('svg[role="img"]')).not.toBeNull()
    expect(solusEnd?.textContent).toBe('')
  })

  it('starts idle with a Connect action that begins the flow', () => {
    const handlers = renderWizard(OAUTH_PICK)
    fireEvent.click(screen.getByRole('button', { name: 'Connect GitHub' }))
    expect(handlers.onBegin).toHaveBeenCalledTimes(1)
  })

  it('shows the live engine label and marks the busy step current', () => {
    renderWizard(OAUTH_PICK, {
      phase: 'busy',
      stage: 'configure',
      label: 'Discovering repositories…'
    })
    expect(screen.getByText('Discovering repositories…')).toBeTruthy()
    const rail = screen.getByLabelText('Connect steps')
    expect(rail.querySelector('[aria-current="step"]')?.textContent).toBe('Pick repositories')
  })

  it('renders the selection picker when the flow offers items', () => {
    const handlers = renderWizard(OAUTH_PICK, {
      phase: 'busy',
      stage: 'configure',
      selectable: [{ id: 'a/one', name: 'a/one' }],
      selectionMode: 'single'
    })
    fireEvent.change(screen.getByLabelText('Choose an item to track'), {
      target: { value: 'a/one' }
    })
    expect(handlers.onSelect).toHaveBeenCalledWith([{ id: 'a/one', name: 'a/one' }])
  })

  it('renders the details form, masking secret-looking fields', () => {
    const handlers = renderWizard(OAUTH_FIELDS, {
      phase: 'busy',
      stage: 'configure',
      configFields: ['document_id', 'license_key']
    })
    const docField = screen.getByLabelText('Document id')
    const licenseField = screen.getByLabelText('License key')
    expect((docField as HTMLInputElement).type).toBe('text')
    expect((licenseField as HTMLInputElement).type).toBe('password')
    fireEvent.change(docField, { target: { value: 'd1' } })
    fireEvent.change(licenseField, { target: { value: 'k1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(handlers.onSubmitConfig).toHaveBeenCalledWith({ document_id: 'd1', license_key: 'k1' })
  })
}

function registerWizardInputsTests(): void {
  it('will not submit a partially filled details form', () => {
    const handlers = renderWizard(OAUTH_FIELDS, {
      phase: 'busy',
      stage: 'configure',
      configFields: ['document_id', 'license_key']
    })
    fireEvent.change(screen.getByLabelText('Document id'), { target: { value: 'd1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(handlers.onSubmitConfig).not.toHaveBeenCalled()
  })

  it('lets a multi-select picker submit an empty selection (connected but idle)', () => {
    const handlers = renderWizard(OAUTH_PICK, {
      phase: 'busy',
      stage: 'configure',
      selectable: [{ id: 'docA', name: 'Rover chassis' }],
      selectionMode: 'multi'
    })
    fireEvent.click(screen.getByRole('button', { name: /track none/i }))
    expect(handlers.onSelect).toHaveBeenCalledWith([])
  })

  it('starts the grant choice on the connector’s own default, not the widest', () => {
    renderWizard(OAUTH_ACCESS, {
      phase: 'busy',
      stage: 'access',
      accessModes: OAUTH_ACCESS.accessModes!
    })
    expect((screen.getByLabelText('Read-only') as HTMLInputElement).checked).toBe(true)
  })

  it('renders the grant choice with descriptions and confirms the chosen mode', () => {
    const handlers = renderWizard(OAUTH_ACCESS, {
      phase: 'busy',
      stage: 'access',
      accessModes: OAUTH_ACCESS.accessModes!
    })
    expect(screen.getByText('Read and change models')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Read and edit'))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(handlers.onChooseAccess).toHaveBeenCalledWith('write')
  })

  it('lets a committed-export connector pick its files and hands over the FILES unread', () => {
    const handlers = renderWizard(EXPORT_FILE)
    const input = screen.getByLabelText('Choose a netlist export or board file') as HTMLInputElement
    const netlist = new File(['<netlist/>'], 'power-board.xml', { type: 'text/xml' })
    const board = new File(['(kicad_pcb)'], 'power-board.kicad_pcb')
    const text = vi.spyOn(netlist, 'text')
    fireEvent.change(input, { target: { files: [netlist, board] } })
    expect(handlers.onPickFiles).toHaveBeenCalledWith([netlist, board])
    // The wizard never reads the files — the glue validates size FIRST.
    expect(text).not.toHaveBeenCalled()
  })

  it('offers kicad a multi-file input accepting netlists and boards, with the schematic hint', () => {
    renderWizard(EXPORT_FILE)
    const input = screen.getByLabelText('Choose a netlist export or board file') as HTMLInputElement
    expect(input.multiple).toBe(true)
    expect(input.accept.split(',')).toEqual(['.xml', '.net', '.kicad_pcb'])
    expect(screen.getByRole('button', { name: /choose netlist \/ board file/i })).toBeTruthy()
    expect(screen.getByText(KICAD_HINT)).toBeTruthy()
  })
}

function registerWizardRecoveryTests(): void {
  it('keeps the single netlist pick for other export connectors, without the kicad hint', () => {
    const handlers = renderWizard(SINGLE_EXPORT_FILE)
    const input = screen.getByLabelText('Choose a committed netlist export') as HTMLInputElement
    expect(input.multiple).toBe(false)
    expect(input.accept).toBe('.xml,.net')
    expect(screen.queryByText(KICAD_HINT)).toBeNull()
    const file = new File(['<netlist/>'], 'design.xml')
    fireEvent.change(input, { target: { files: [file] } })
    expect(handlers.onPickFiles).toHaveBeenCalledWith([file])
    expect(screen.getByRole('button', { name: /choose export file/i })).toBeTruthy()
  })

  it('ignores an empty file dialog (cancelled pick)', () => {
    const handlers = renderWizard(EXPORT_FILE)
    const input = screen.getByLabelText('Choose a netlist export or board file')
    fireEvent.change(input, { target: { files: [] } })
    expect(handlers.onPickFiles).not.toHaveBeenCalled()
  })

  it('retries a committed-export connector with the file picker, never the OAuth path', () => {
    const handlers = renderWizard(EXPORT_FILE, { phase: 'error', error: 'Sync failed.' })
    expect(screen.getByText('Sync failed.')).toBeTruthy()
    const again = screen.getByRole('button', { name: /choose netlist \/ board file/i })
    expect(again).toBeTruthy()
    fireEvent.click(again)
    expect(handlers.onBegin).not.toHaveBeenCalled()
  })

  it('shows the honest error and retries through onBegin', () => {
    const handlers = renderWizard(OAUTH_PICK, {
      phase: 'error',
      error: 'GitHub sign-in was cancelled.'
    })
    expect(screen.getByText('GitHub sign-in was cancelled.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(handlers.onBegin).toHaveBeenCalledTimes(1)
  })

  it('celebrates done with the real result and closes', () => {
    const handlers = renderWizard(OAUTH_PICK, {
      phase: 'done',
      result: 'Connected — 214 entities indexed'
    })
    expect(screen.getByText('Connected — 214 entities indexed')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(handlers.onClose).toHaveBeenCalledTimes(1)
  })

  it('closes from the X control', () => {
    const handlers = renderWizard(OAUTH_PICK)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(handlers.onClose).toHaveBeenCalledTimes(1)
  })
}

function registerWizardModesTests(): void {
  it('respects SOL mode: Guide teaches, Expert is terse (ADR-016)', () => {
    const { unmount } = render(
      <ConnectWizardModal
        entry={OAUTH_PICK}
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    const guideCopy = screen.getByTestId('cw-instruction').textContent ?? ''
    unmount()
    useSettingsStore.getState().setSolMode('Expert')
    renderWizard(OAUTH_PICK)
    const expertCopy = screen.getByTestId('cw-instruction').textContent ?? ''
    expect(guideCopy).not.toBe(expertCopy)
    expect(guideCopy.length).toBeGreaterThan(expertCopy.length)
  })
}

describe('ConnectWizardModal — team GitHub organization (SOLUSDEV-216)', () => {
  const INSTALLATION = {
    id: 'i1',
    provider: 'github',
    account_login: 'fsae-ev',
    account_type: 'Organization',
    status: 'active'
  } as teamGithub.TeamInstallation
  const REPO = { id: 'fsae-ev/vcu', name: 'fsae-ev/vcu', subtitle: 'private' }

  beforeEach(() => {
    vi.mocked(teamGithub.getTeamInstallation).mockReset()
    vi.mocked(teamGithub.listTeamGithubRepos).mockReset()
    vi.mocked(teamGithub.listTeamGithubRepos).mockResolvedValue({
      items: [REPO],
      total: 1,
      cursor: null
    })
    useTeamPick.setState({ picked: null })
    useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover', teamId: 't1' } })
  })

  function renderTeam(
    entry: CatalogEntry,
    linkedAccount: { login: string | null } | null = null
  ): Handlers {
    const handlers: Handlers = {
      onBegin: vi.fn(),
      onPickFiles: vi.fn(),
      onSelect: vi.fn(),
      onSubmitConfig: vi.fn(),
      onChooseAccess: vi.fn(),
      onClose: vi.fn()
    }
    render(<ConnectWizardModal entry={entry} linkedAccount={linkedAccount} {...handlers} />)
    return handlers
  }

  it('shows the team and account sections and a rail without a sign-in', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue(INSTALLATION)
    renderTeam(OAUTH_PICK, { login: 'maya-k' })

    expect(await screen.findByRole('group', { name: 'FROM FSAE-EV (TEAM)' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'YOUR ACCOUNT · maya-k' })).toBeInTheDocument()
    const rail = screen.getByLabelText('Connect steps')
    expect(rail).toHaveTextContent('Pick repositoriesBuild graph')
    expect(rail).not.toHaveTextContent('Sign in')
  })

  it('picking a team repo stages it and begins', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue(INSTALLATION)
    const handlers = renderTeam(OAUTH_PICK, { login: 'maya-k' })

    fireEvent.click(await screen.findByRole('button', { name: /fsae-ev\/vcu/ }))

    expect(useTeamPick.getState().picked).toEqual(REPO)
    expect(handlers.onBegin).toHaveBeenCalledTimes(1)
  })

  it('picking the account entry begins without staging a team repo', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue(INSTALLATION)
    const handlers = renderTeam(OAUTH_PICK)

    fireEvent.click(await screen.findByRole('button', { name: 'Use my own GitHub account' }))

    expect(useTeamPick.getState().picked).toBeNull()
    expect(handlers.onBegin).toHaveBeenCalledTimes(1)
  })

  it('a suspended installation reads "Suspended on GitHub" and lists nothing', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue({
      ...INSTALLATION,
      status: 'suspended'
    })
    renderTeam(OAUTH_PICK)

    expect(await screen.findByText('Suspended on GitHub')).toBeInTheDocument()
    expect(teamGithub.listTeamGithubRepos).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /fsae-ev\/vcu/ })).not.toBeInTheDocument()
  })

  it('offers the picker again after a failed team bind instead of a dead Retry', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue(INSTALLATION)
    render(
      <ConnectWizardModal
        entry={OAUTH_PICK}
        state={{ phase: 'error', error: 'That repository is not shared.' }}
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByTestId('cw-instruction')).toHaveTextContent('That repository is not shared.')
    expect(await screen.findByRole('button', { name: /fsae-ev\/vcu/ })).toBeInTheDocument()
  })

  it('with no installation the wizard is exactly the legacy one', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockResolvedValue(null)
    renderTeam(OAUTH_PICK)

    await waitFor(() => expect(teamGithub.getTeamInstallation).toHaveBeenCalledWith('t1'))
    expect(screen.getByRole('button', { name: 'Connect GitHub' })).toBeInTheDocument()
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
  })

  it('falls back to the legacy wizard when the installation lookup fails', async () => {
    vi.mocked(teamGithub.getTeamInstallation).mockRejectedValue(new Error('offline'))
    renderTeam(OAUTH_PICK)

    await waitFor(() => expect(teamGithub.getTeamInstallation).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Connect GitHub' })).toBeInTheDocument()
  })

  it('never looks up a team installation for another provider', () => {
    renderTeam(OAUTH_FIELDS)
    expect(teamGithub.getTeamInstallation).not.toHaveBeenCalled()
  })

  it('never looks up an installation in account scope', () => {
    render(
      <ConnectWizardModal
        entry={OAUTH_PICK}
        scope="account"
        onBegin={vi.fn()}
        onPickFiles={vi.fn()}
        onSelect={vi.fn()}
        onSubmitConfig={vi.fn()}
        onChooseAccess={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(teamGithub.getTeamInstallation).not.toHaveBeenCalled()
  })
})
