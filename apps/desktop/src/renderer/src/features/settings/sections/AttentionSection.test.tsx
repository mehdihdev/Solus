import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AttentionSection, type AttentionActions } from './AttentionSection'

function actions(): AttentionActions {
  return {
    openCaptureSettings: vi.fn(),
    recheckCapture: vi.fn(),
    turnOffCapture: vi.fn(),
    openBilling: vi.fn(),
    openAccounts: vi.fn(),
    requestDrivePermissions: vi.fn(),
    turnOffDrive: vi.fn(),
    openDriveApproval: vi.fn()
  }
}

describe('AttentionSection', () => {
  it('renders nothing when nothing needs the user', () => {
    const { container } = render(<AttentionSection items={[]} actions={actions()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('turns blocked capture into an action card with the path and working buttons', async () => {
    const a = actions()
    render(
      <AttentionSection
        items={[{ kind: 'capture', message: 'Needs Screen Recording.', canOpenSettings: true }]}
        actions={a}
      />
    )
    expect(screen.getByRole('group', { name: "SOL can't see your screen yet" })).toBeInTheDocument()
    expect(screen.getByText(/Privacy & Security › Screen Recording/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open Screen Recording settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Recheck' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turn off screen capture' }))
    expect(a.openCaptureSettings).toHaveBeenCalled()
    expect(a.recheckCapture).toHaveBeenCalled()
    expect(a.turnOffCapture).toHaveBeenCalled()
  })

  it('shows the platform message and no settings button where there is no pane (Wayland)', () => {
    render(
      <AttentionSection
        items={[{ kind: 'capture', message: 'Wayland blocks capture.', canOpenSettings: false }]}
        actions={actions()}
      />
    )
    expect(screen.getByText('Wayland blocks capture.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open Screen Recording settings' })).toBeNull()
  })

  it('counts down a trial and sends the user to Billing', async () => {
    const a = actions()
    const { rerender } = render(
      <AttentionSection items={[{ kind: 'trial', days: 9, ended: false }]} actions={a} />
    )
    expect(screen.getByText('Your trial ends in 9 days')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Choose a plan' }))
    expect(a.openBilling).toHaveBeenCalled()
    rerender(<AttentionSection items={[{ kind: 'trial', days: 0, ended: true }]} actions={a} />)
    expect(screen.getByText('Your trial has ended')).toBeInTheDocument()
  })

  it('asks to reconnect a broken account on Home', async () => {
    const a = actions()
    render(
      <AttentionSection
        items={[{ kind: 'reconnect', connectionId: 'c1', provider: 'onshape', login: 'mk' }]}
        actions={a}
      />
    )
    expect(screen.getByText('Reconnect Onshape (@mk)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reconnect' }))
    expect(a.openAccounts).toHaveBeenCalled()
  })
})

describe('AttentionSection — drive (SOLUSDEV-319)', () => {
  it('names the helper and the missing permissions, and asks macOS from the fix', async () => {
    const a = actions()
    render(
      <AttentionSection
        items={[{ kind: 'drive', missing: ['Accessibility', 'Screen Recording'] }]}
        actions={a}
      />
    )
    const card = screen.getByRole('group', { name: 'SolusInput needs permission' })
    expect(card).toHaveTextContent(/SolusInput/)
    expect(card).toHaveTextContent(/Accessibility and Screen Recording/)
    expect(screen.getByText(/Privacy & Security › Accessibility › SolusInput/)).toBeInTheDocument()
    expect(
      screen.getByText(/Privacy & Security › Screen Recording › SolusInput/)
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ask macOS for permission' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turn off mouse and keyboard' }))
    expect(a.requestDrivePermissions).toHaveBeenCalled()
    expect(a.turnOffDrive).toHaveBeenCalled()
  })

  it('asks to allow SolusInput in Login Items and opens that pane', async () => {
    const a = actions()
    render(<AttentionSection items={[{ kind: 'drive_approval' }]} actions={a} />)
    const card = screen.getByRole('group', { name: 'Allow SolusInput in Login Items' })
    expect(card).toHaveTextContent(
      'macOS asks you to allow SolusInput to run in the background before SOL can use your mouse and keyboard.'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Open Login Items' }))
    await userEvent.click(screen.getByRole('button', { name: 'Turn off mouse and keyboard' }))
    expect(a.openDriveApproval).toHaveBeenCalled()
    expect(a.turnOffDrive).toHaveBeenCalled()
  })
})
