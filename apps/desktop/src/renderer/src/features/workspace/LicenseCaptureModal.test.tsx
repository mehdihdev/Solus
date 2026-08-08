// BYO-license capture modal (SOLUSDEV-102 / MCP-05): one masked input per
// license_secrets key NAME, submit via solus.bridge.submitLicense, and the
// hygiene invariant — the secret VALUE (a sentinel) never reaches any Zustand
// store, any console output, or a reopened modal.
import { describe, it, expect, beforeEach, afterEach, vi, type MockInstance } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { LicenseCaptureModal } from './LicenseCaptureModal'
import { useShellStore } from './shellStore'
import { useAuthStore } from '../../store/authStore'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

const SENTINEL = 'SENTINEL-NOT-A-REAL-LICENSE'

type SubmitLicense = (
  server: string,
  secrets: Record<string, string>
) => Promise<{ ok: boolean; error?: string }>

const submitLicense = vi.fn<SubmitLicense>()

function installBridge(): void {
  ;(window as unknown as { solus?: unknown }).solus = { bridge: { submitLicense } }
}

beforeEach(() => {
  vi.clearAllMocks()
  submitLicense.mockResolvedValue({ ok: true })
  installBridge()
})

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('LicenseCaptureModal', () => {
  it('renders one masked input per license_secrets key NAME', () => {
    const { container } = render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
    const input = screen.getByLabelText('altium_license')
    expect(input).toHaveAttribute('type', 'password')
    expect(container.querySelectorAll('input')).toHaveLength(1)
  })

  it('bounds each input length so an oversize value never reaches the relay (M4)', () => {
    render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
    expect(screen.getByLabelText('altium_license')).toHaveAttribute('maxLength', '4096')
  })

  it('submits the entered value through bridge.submitLicense and shows the ack by key name', async () => {
    render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
    await userEvent.type(screen.getByLabelText('altium_license'), SENTINEL)
    await userEvent.click(screen.getByRole('button', { name: /add license/i }))
    expect(submitLicense).toHaveBeenCalledTimes(1)
    expect(submitLicense).toHaveBeenCalledWith('altium', { altium_license: SENTINEL })
    // Ack surfaced by key NAME (the value never renders anywhere).
    expect(await screen.findByText(/altium_license/)).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(SENTINEL))).not.toBeInTheDocument()
  })

  it('shows the relay error when the companion is not running', async () => {
    submitLicense.mockResolvedValue({ ok: false, error: 'companion not running' })
    render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
    await userEvent.type(screen.getByLabelText('altium_license'), SENTINEL)
    await userEvent.click(screen.getByRole('button', { name: /add license/i }))
    expect(await screen.findByText(/companion not running/)).toBeInTheDocument()
  })

  it('explains itself when the desktop bridge is unavailable', async () => {
    delete (window as unknown as { solus?: unknown }).solus
    render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
    await userEvent.type(screen.getByLabelText('altium_license'), SENTINEL)
    await userEvent.click(screen.getByRole('button', { name: /add license/i }))
    expect(await screen.findByText(/desktop app/i)).toBeInTheDocument()
  })

  it('degrades honestly for a server whose key names are not known client-side', () => {
    render(<LicenseCaptureModal server="mystery" onClose={() => undefined} />)
    expect(screen.getByText(/key names/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add license/i })).not.toBeInTheDocument()
  })
})

describe('LicenseCaptureModal hygiene', () => {
  it('clears inputs on close and keeps the value out of every surviving store', async () => {
    function Harness(): React.JSX.Element {
      const [open, setOpen] = useState(true)
      return (
        <div>
          <button onClick={() => setOpen(true)}>reopen</button>
          {open && <LicenseCaptureModal server="altium" onClose={() => setOpen(false)} />}
        </div>
      )
    }
    render(<Harness />)
    await userEvent.type(screen.getByLabelText('altium_license'), SENTINEL)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByLabelText('altium_license')).not.toBeInTheDocument())
    // The value must not survive the modal in ANY store that outlives it.
    for (const store of [useShellStore, useAuthStore, useSettingsStore, useWorkspaceStore]) {
      expect(JSON.stringify(store.getState())).not.toContain(SENTINEL)
    }
    await userEvent.click(screen.getByRole('button', { name: 'reopen' }))
    expect(screen.getByLabelText('altium_license')).toHaveValue('')
  })

  it('never writes the secret value to the console on any path', async () => {
    const spies: MockInstance[] = (['log', 'warn', 'error', 'info', 'debug'] as const).map(
      (level) => vi.spyOn(console, level).mockImplementation(() => undefined)
    )
    try {
      submitLicense.mockResolvedValueOnce({ ok: false, error: 'companion not running' })
      render(<LicenseCaptureModal server="altium" onClose={() => undefined} />)
      await userEvent.type(screen.getByLabelText('altium_license'), SENTINEL)
      await userEvent.click(screen.getByRole('button', { name: /add license/i }))
      await screen.findByText(/companion not running/)
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(JSON.stringify(call)).not.toContain(SENTINEL)
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore())
    }
  })
})
