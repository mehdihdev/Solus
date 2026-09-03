// SOLUSDEV-235 — the extension detail page: header actions + tabs.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExtensionDetail } from './ExtensionDetail'
import { EXTENSION_CATALOG } from './extensions.catalog'
import { buildView, DEFAULT_INSTALL_STATE } from './extensionLogic'
import type { ExtensionInstallState, ExtensionView } from './extension.types'
import type { ExtensionActions } from './useExtensions'

function viewOf(
  id: string,
  state: Partial<ExtensionInstallState> = {},
  connected: string[] = []
): ExtensionView {
  const manifest = EXTENSION_CATALOG.find((m) => m.id === id)!
  return buildView(manifest, { ...DEFAULT_INSTALL_STATE, ...state }, new Set(connected as never[]))
}

function actions(): ExtensionActions {
  return { install: vi.fn(), uninstall: vi.fn(), setEnabled: vi.fn(), setRunFrequency: vi.fn() }
}

describe('ExtensionDetail', () => {
  it('shows the header meta with an honest install count', () => {
    render(
      <ExtensionDetail
        view={viewOf('experiments', { installed: true })}
        actions={actions()}
        onBack={vi.fn()}
      />
    )
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeInTheDocument()
    expect(screen.getByText(/Solus · v1\.0\.0 · — installs · updated/)).toBeInTheDocument()
    expect(screen.getByText('SOLUS')).toBeInTheDocument()
  })

  it('offers Disable + Uninstall when installed, and confirms the uninstall', async () => {
    const a = actions()
    render(
      <ExtensionDetail
        view={viewOf('experiments', { installed: true })}
        actions={a}
        onBack={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Disable' }))
    expect(a.setEnabled).toHaveBeenCalledWith('experiments', false)
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall' }))
    expect(screen.getByText(/Uninstall Experiments\?/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Uninstall extension' }))
    expect(a.uninstall).toHaveBeenCalledWith('experiments')
  })

  it('offers Enable when installed but disabled', async () => {
    const a = actions()
    render(
      <ExtensionDetail
        view={viewOf('experiments', { installed: true, enabled: false })}
        actions={a}
        onBack={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Enable' }))
    expect(a.setEnabled).toHaveBeenCalledWith('experiments', true)
  })

  it('offers Install when available and blocks it while a source is missing', async () => {
    const a = actions()
    const { rerender } = render(
      <ExtensionDetail view={viewOf('bom', {}, ['eda'])} actions={a} onBack={vi.fn()} />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(a.install).toHaveBeenCalledWith('bom')
    rerender(<ExtensionDetail view={viewOf('bom')} actions={a} onBack={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
    expect(screen.getByText('NEEDS EDA')).toBeInTheDocument()
  })

  it('switches tabs and goes back', async () => {
    const onBack = vi.fn()
    render(
      <ExtensionDetail
        view={viewOf('experiments', { installed: true })}
        actions={actions()}
        onBack={onBack}
      />
    )
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('WHAT IT ADDS')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Settings' }))
    expect(screen.getByRole('switch', { name: 'Enable in this project' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Permissions' }))
    expect(screen.getByText('Read the context graph')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Store' }))
    expect(onBack).toHaveBeenCalledOnce()
  })
})
