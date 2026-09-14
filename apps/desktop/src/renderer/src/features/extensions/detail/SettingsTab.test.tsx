// SOLUSDEV-235 — detail › Settings, rendered from the manifest's fields.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsTab } from './SettingsTab'
import { fakeActions, manifest, viewOf } from '../testing/fixtures'

describe('SettingsTab', () => {
  registerExtensionSettingsEditsTests()
  registerExtensionSettingsAvailabilityTests()
})

function registerExtensionSettingsEditsTests(): void {
  it('toggles enablement for this project', async () => {
    const a = fakeActions()
    render(<SettingsTab view={viewOf({ install: {} })} actions={a} />)
    const sw = screen.getByRole('switch', { name: 'Enable in this project' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(sw)
    expect(a.setEnabled).toHaveBeenCalledWith('bom', false)
  })

  it('renders one control per manifest field, seeded from stored values over defaults', () => {
    render(<SettingsTab view={viewOf({ install: {} })} actions={fakeActions()} />)
    expect(screen.getByRole('combobox', { name: 'Run frequency' })).toHaveValue('hourly')
    expect(screen.getByRole('switch', { name: 'Include DNP parts' })).toHaveAttribute(
      'aria-checked',
      'false'
    )
    const rows = screen.getByRole('spinbutton', { name: 'Max rows' })
    expect(rows).toHaveValue(200)
    expect(rows).toHaveAttribute('min', '10')
    expect(rows).toHaveAttribute('max', '1000')
    expect(screen.getByRole('textbox', { name: 'Currency' })).toHaveValue('USD')
  })

  it('saves the whole settings object, debounced, after a change', async () => {
    const a = fakeActions()
    render(<SettingsTab view={viewOf({ install: {} })} actions={a} />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Run frequency' }), 'daily')
    await userEvent.click(screen.getByRole('switch', { name: 'Include DNP parts' }))
    await waitFor(() => expect(a.setSettings).toHaveBeenCalledTimes(1))
    expect(a.setSettings).toHaveBeenCalledWith('bom', {
      refresh: 'daily',
      include_dnp: true,
      max_rows: 200,
      currency: 'USD'
    })
  })

  it('saves typed text and numbers once typing pauses', async () => {
    const a = fakeActions()
    render(<SettingsTab view={viewOf({ install: {} })} actions={a} />)
    const currency = screen.getByRole('textbox', { name: 'Currency' })
    await userEvent.clear(currency)
    await userEvent.type(currency, 'EUR')
    const rows = screen.getByRole('spinbutton', { name: 'Max rows' })
    await userEvent.clear(rows)
    await userEvent.type(rows, '50')
    await waitFor(() => expect(a.setSettings).toHaveBeenCalled())
    expect(a.setSettings).toHaveBeenLastCalledWith(
      'bom',
      expect.objectContaining({ currency: 'EUR', max_rows: 50 })
    )
  })
}

function registerExtensionSettingsAvailabilityTests(): void {
  it('shows the refusal when the server rejects a value', async () => {
    const a = fakeActions({
      setSettings: vi.fn(async () => ({
        ok: false,
        code: 'validation_error',
        message: 'Solus rejected that request. Check the values and try again.'
      }))
    })
    render(<SettingsTab view={viewOf({ install: {} })} actions={a} />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Run frequency' }), 'daily')
    expect(await screen.findByRole('alert')).toHaveTextContent(/rejected/)
  })

  it('explains the project scope of these settings', () => {
    render(<SettingsTab view={viewOf({ install: {} })} actions={fakeActions()} />)
    expect(screen.getByText(/Settings apply to this project only/)).toBeInTheDocument()
  })

  it('locks the controls until the extension is installed', () => {
    render(<SettingsTab view={viewOf()} actions={fakeActions()} />)
    expect(screen.getByRole('switch', { name: 'Enable in this project' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Run frequency' })).toBeDisabled()
    expect(screen.getByText(/Install this extension to change its settings/)).toBeInTheDocument()
  })

  it('says so when the manifest declares no settings', () => {
    render(
      <SettingsTab
        view={viewOf({ manifest: manifest({ settings: { fields: [] } }), install: {} })}
        actions={fakeActions()}
      />
    )
    expect(screen.getByText(/no settings of its own/)).toBeInTheDocument()
  })
}
