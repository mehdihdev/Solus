// SOLUSDEV-235 — the permissions step (extensions-runtime wireflow §1).
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GrantPermissionsModal, type GrantPermissionsModalProps } from './GrantPermissionsModal'

function props(over: Partial<GrantPermissionsModalProps> = {}): GrantPermissionsModalProps {
  return {
    name: 'BOM',
    version: '1.2.0',
    publisher: 'Solus',
    verified: true,
    mode: 'install',
    scopes: ['graph.read', 'sources.read'],
    network: ['https://api.octopart.com'],
    privacyPolicyUrl: '/extensions/bom/versions/1.2.0/assets/PRIVACY.md',
    busy: false,
    error: null,
    onGrant: vi.fn(),
    onCancel: vi.fn(),
    ...over
  }
}

describe('GrantPermissionsModal', () => {
  it('lists the declared scopes in manifest order with Solus copy and the raw scope', () => {
    render(<GrantPermissionsModal {...props()} />)
    expect(screen.getByRole('dialog', { name: 'Install BOM' })).toBeInTheDocument()
    expect(screen.getByText('BOM asks for')).toBeInTheDocument()
    const titles = screen.getAllByTestId('grant-scope').map((el) => el.textContent)
    expect(titles[0]).toMatch(/Read the context model/)
    expect(titles[0]).toMatch(/graph\.read/)
    expect(titles[1]).toMatch(/List connected sources/)
    expect(screen.getByText('It may connect to')).toBeInTheDocument()
    expect(screen.getByText('https://api.octopart.com')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'https://api.octopart.com' })).not.toBeInTheDocument()
    expect(screen.getByText(/never receives your credentials/)).toBeInTheDocument()
  })

  it('links the privacy policy when the bundle ships one', () => {
    const { rerender } = render(<GrantPermissionsModal {...props()} />)
    expect(screen.getByRole('link', { name: /Privacy policy/ })).toHaveAttribute(
      'href',
      expect.stringMatching(/\/extensions\/bom\/versions\/1\.2\.0\/assets\/PRIVACY\.md$/)
    )
    rerender(<GrantPermissionsModal {...props({ privacyPolicyUrl: null })} />)
    expect(screen.queryByRole('link', { name: /Privacy policy/ })).not.toBeInTheDocument()
  })

  it('grants all-or-nothing and cancels without granting', async () => {
    const p = props()
    render(<GrantPermissionsModal {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Grant and install' }))
    expect(p.onGrant).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(p.onCancel).toHaveBeenCalledOnce()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('closes from ✕ and Escape', async () => {
    const p = props()
    render(<GrantPermissionsModal {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await userEvent.keyboard('{Escape}')
    expect(p.onCancel).toHaveBeenCalledTimes(2)
  })

  it('reads plainly when nothing is asked for', () => {
    render(
      <GrantPermissionsModal {...props({ scopes: [], network: [], privacyPolicyUrl: null })} />
    )
    expect(screen.getByText(/BOM asks for nothing/)).toBeInTheDocument()
    expect(screen.getByText(/entirely inside its sandbox/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument()
    expect(screen.queryByText('It may connect to')).not.toBeInTheDocument()
  })

  it('titles an update and lists only the additions', () => {
    render(
      <GrantPermissionsModal
        {...props({ mode: 'update', version: '1.3.0', scopes: ['telemetry.read'], network: [] })}
      />
    )
    expect(screen.getByRole('dialog', { name: 'Update BOM' })).toBeInTheDocument()
    expect(screen.getByText('1.3.0 additionally asks for')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Grant and update' })).toBeInTheDocument()
  })

  it('disables the grant button while busy and shows an inline error', () => {
    const { rerender } = render(<GrantPermissionsModal {...props({ busy: true })} />)
    expect(screen.getByRole('button', { name: 'Installing…' })).toBeDisabled()
    rerender(<GrantPermissionsModal {...props({ error: "Couldn't install. Try again." })} />)
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't install. Try again.")
  })
})
