// SOLUSDEV-235 — detail › Settings.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsTab } from './SettingsTab'
import { EXTENSION_CATALOG } from '../extensions.catalog'
import { buildView, DEFAULT_INSTALL_STATE } from '../extensionLogic'
import type { ExtensionInstallState, ExtensionView } from '../extension.types'
import type { ExtensionActions } from '../useExtensions'

function viewOf(id: string, state: Partial<ExtensionInstallState> = {}): ExtensionView {
  const manifest = EXTENSION_CATALOG.find((m) => m.id === id)!
  return buildView(manifest, { ...DEFAULT_INSTALL_STATE, ...state }, new Set())
}

function actions(): ExtensionActions {
  return { install: vi.fn(), uninstall: vi.fn(), setEnabled: vi.fn(), setRunFrequency: vi.fn() }
}

describe('SettingsTab', () => {
  it('toggles enablement for this project', async () => {
    const a = actions()
    render(<SettingsTab view={viewOf('experiments', { installed: true })} actions={a} />)
    const sw = screen.getByRole('switch', { name: 'Enable in this project' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(sw)
    expect(a.setEnabled).toHaveBeenCalledWith('experiments', false)
  })

  it('changes the run frequency', async () => {
    const a = actions()
    render(<SettingsTab view={viewOf('experiments', { installed: true })} actions={a} />)
    const select = screen.getByRole('combobox', { name: 'Run frequency' })
    expect(select).toHaveValue('every_sync')
    await userEvent.selectOptions(select, 'daily')
    expect(a.setRunFrequency).toHaveBeenCalledWith('experiments', 'daily')
  })

  it('explains the project scope of these settings', () => {
    render(<SettingsTab view={viewOf('experiments', { installed: true })} actions={actions()} />)
    expect(screen.getByText(/Settings apply to this project only/)).toBeInTheDocument()
  })

  it('locks the controls until the extension is installed', () => {
    render(<SettingsTab view={viewOf('bom')} actions={actions()} />)
    expect(screen.getByRole('switch')).toBeDisabled()
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(screen.getByText(/Install this extension to change its settings/)).toBeInTheDocument()
  })
})
