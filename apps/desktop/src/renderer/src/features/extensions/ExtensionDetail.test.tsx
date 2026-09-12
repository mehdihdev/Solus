// SOLUSDEV-235 — the extension detail page: header actions, the permissions
// step, the update flow, and the tabs.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExtensionDetail } from './ExtensionDetail'
import { fakeActions, manifest, viewOf } from './testing/fixtures'
import type { ExtensionActionResult } from './extensionActions'

const fail = (over: Partial<ExtensionActionResult>): ExtensionActionResult =>
  ({ ok: false, code: 'x', message: 'x', ...over }) as ExtensionActionResult

describe('ExtensionDetail — header', () => {
  it('marks a first-party bundle and offers the pin (STORE ST3)', () => {
    const firstParty = manifest({ schema_version: 2, backend: { capability: 'bom', routes: true } })
    render(
      <ExtensionDetail
        view={viewOf({ manifest: firstParty, install: {} })}
        actions={fakeActions()}
        onBack={vi.fn()}
      />
    )
    expect(screen.getByTestId('first-party-badge')).toHaveTextContent('FIRST-PARTY')
    expect(screen.getByRole('button', { name: 'Pin for all projects' })).toBeInTheDocument()
  })

  it('shows no first-party badge for a community bundle', () => {
    render(
      <ExtensionDetail view={viewOf({ install: {} })} actions={fakeActions()} onBack={vi.fn()} />
    )
    expect(screen.queryByTestId('first-party-badge')).toBeNull()
  })

  it('shows the meta line with the real install count', () => {
    render(
      <ExtensionDetail view={viewOf({ install: {} })} actions={fakeActions()} onBack={vi.fn()} />
    )
    expect(screen.getByRole('heading', { name: 'BOM' })).toBeInTheDocument()
    expect(screen.getByText(/Solus · v1\.2\.0 · 412 installs · updated/)).toBeInTheDocument()
  })

  it('renders an honest dash when the catalog reports no count', () => {
    render(
      <ExtensionDetail
        view={viewOf({ catalog: { install_count: null as never } })}
        actions={fakeActions()}
        onBack={vi.fn()}
      />
    )
    expect(screen.getByText(/— installs/)).toBeInTheDocument()
  })

  it('offers Disable + Uninstall when installed, and confirms the uninstall', async () => {
    const a = fakeActions()
    const onBack = vi.fn()
    render(<ExtensionDetail view={viewOf({ install: {} })} actions={a} onBack={onBack} />)
    await userEvent.click(screen.getByRole('button', { name: 'Disable' }))
    expect(a.setEnabled).toHaveBeenCalledWith('bom', false)
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall' }))
    expect(screen.getByText(/Uninstall BOM\?/)).toBeInTheDocument()
    // SOLUSDEV-246: uninstall leaves no trace — the copy says so.
    expect(screen.getByText(/the graph data it added leave this project/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall extension' }))
    expect(a.uninstall).toHaveBeenCalledWith('bom')
    await waitFor(() => expect(onBack).toHaveBeenCalledOnce())
  })

  it('stays on the page and explains when the uninstall is refused', async () => {
    const a = fakeActions({
      uninstall: vi.fn(async () =>
        fail({ code: 'forbidden', message: 'Only project members can change extensions here.' })
      )
    })
    const onBack = vi.fn()
    render(<ExtensionDetail view={viewOf({ install: {} })} actions={a} onBack={onBack} />)
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall' }))
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall extension' }))
    expect(await screen.findByText(/Only project members/)).toBeInTheDocument()
    expect(onBack).not.toHaveBeenCalled()
  })

  it('offers Enable when installed but disabled', async () => {
    const a = fakeActions()
    render(
      <ExtensionDetail
        view={viewOf({ install: { enabled: false } })}
        actions={a}
        onBack={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Enable' }))
    expect(a.setEnabled).toHaveBeenCalledWith('bom', true)
  })

  it('blocks Install while a source is missing', () => {
    render(<ExtensionDetail view={viewOf()} actions={fakeActions()} onBack={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
    expect(screen.getByText('NEEDS EDA')).toBeInTheDocument()
  })

  it('blocks Install when the team blocks the extension', () => {
    render(
      <ExtensionDetail
        view={viewOf({ connected: ['eda'], blocked: true })}
        actions={fakeActions()}
        onBack={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
    expect(screen.getByText('Blocked by your team')).toBeInTheDocument()
  })

  it('waits for the manifest before offering Install', () => {
    const view = { ...viewOf({ connected: ['eda'] }), manifest: null }
    render(<ExtensionDetail view={view} actions={fakeActions()} onBack={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
  })

  it('notes when an installed version has left the catalog', () => {
    const view = viewOf({ install: {} })
    render(
      <ExtensionDetail
        view={{ ...view, catalog: { ...view.catalog, inCatalog: false } }}
        actions={fakeActions()}
        onBack={vi.fn()}
      />
    )
    expect(screen.getByText(/no longer in the catalog/)).toBeInTheDocument()
  })
})

describe('ExtensionDetail — install flow', () => {
  it('opens the permissions step and grants the declared set, all or nothing', async () => {
    const a = fakeActions()
    render(<ExtensionDetail view={viewOf({ connected: ['eda'] })} actions={a} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(screen.getByRole('dialog', { name: 'Install BOM' })).toBeInTheDocument()
    expect(screen.getByText('Read the workspace graph')).toBeInTheDocument()
    expect(screen.getByText('https://api.octopart.com')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Grant and install' }))
    expect(a.install).toHaveBeenCalledWith('bom', {
      scopes: ['graph.read', 'sources.read'],
      network: ['https://api.octopart.com']
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('creates nothing on Cancel', async () => {
    const a = fakeActions()
    render(<ExtensionDetail view={viewOf({ connected: ['eda'] })} actions={a} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(a.install).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the server refusal inside the step', async () => {
    const a = fakeActions({
      install: vi.fn(async () =>
        fail({ code: 'extension_blocked', message: 'Blocked by your team.' })
      )
    })
    render(<ExtensionDetail view={viewOf({ connected: ['eda'] })} actions={a} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Grant and install' }))
    expect(await screen.findByText('Blocked by your team.')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('surfaces the bundle note after a successful install', async () => {
    const a = fakeActions({
      install: vi.fn(
        async () =>
          ({ ok: true, bundle: 'deferred', note: 'Bundle later.' }) as ExtensionActionResult
      )
    })
    render(<ExtensionDetail view={viewOf({ connected: ['eda'] })} actions={a} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Grant and install' }))
    expect(await screen.findByText('Bundle later.')).toBeInTheDocument()
  })
})

describe('ExtensionDetail — update flow', () => {
  const updatable = viewOf({
    install: { update_available: { version: '1.3.0', widens_permissions: true } }
  })

  it('shows the update in the meta line and updates with the current grants', async () => {
    const a = fakeActions()
    render(<ExtensionDetail view={updatable} actions={a} onBack={vi.fn()} />)
    expect(screen.getByText(/v1\.2\.0 → 1\.3\.0 available/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Update to 1.3.0' }))
    expect(a.update).toHaveBeenCalledWith('bom')
  })

  it('re-asks only for the new scopes when the server answers grants_required', async () => {
    const a = fakeActions({
      update: vi
        .fn<(slug: string, grants?: unknown) => Promise<ExtensionActionResult>>()
        .mockResolvedValueOnce(
          fail({
            code: 'grants_required',
            message: 'more',
            grantsRequired: { scopes: ['telemetry.read'], network: ['https://x.example'] }
          })
        )
        .mockResolvedValueOnce({ ok: true })
    })
    render(<ExtensionDetail view={updatable} actions={a} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Update to 1.3.0' }))
    expect(await screen.findByRole('dialog', { name: 'Update BOM' })).toBeInTheDocument()
    expect(screen.getByText('Read telemetry streams')).toBeInTheDocument()
    expect(screen.queryByText('Read the workspace graph')).not.toBeInTheDocument()
    expect(screen.getByText('https://x.example')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Grant and update' }))
    expect(a.update).toHaveBeenLastCalledWith('bom', {
      scopes: ['graph.read', 'sources.read', 'telemetry.read'],
      network: ['https://api.octopart.com', 'https://x.example']
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

describe('ExtensionDetail — tabs', () => {
  it('switches tabs and goes back', async () => {
    const onBack = vi.fn()
    render(
      <ExtensionDetail view={viewOf({ install: {} })} actions={fakeActions()} onBack={onBack} />
    )
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('WHAT IT ADDS')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Settings' }))
    expect(screen.getByRole('switch', { name: 'Enable in this project' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Permissions' }))
    expect(screen.getByText('Read the workspace graph')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Store' }))
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('renders a manifest-less extension without crashing', async () => {
    const view = { ...viewOf({ manifest: manifest() }), manifest: null }
    render(<ExtensionDetail view={view} actions={fakeActions()} onBack={vi.fn()} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Permissions' }))
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
  })
})
