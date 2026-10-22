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
    openAccounts: vi.fn()
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
