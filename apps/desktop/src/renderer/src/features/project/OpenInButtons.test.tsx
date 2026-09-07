// SOLUSDEV-249 (I2) — the Open-in button set shared by the LOCAL FOLDER card
// and the graph inspector: one labelled button per open target, disabled with
// the honest reason, and the tool's own refusal shown inline.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { COMPANION_OFFLINE_NOTE } from './localFolder.constants'
import { OpenInButtons } from './OpenInButtons'

describe('OpenInButtons', () => {
  it('renders one labelled button per target and opens through the callback', async () => {
    const onOpen = vi.fn(async () => ({ launched: true, tool: 'kicad' as const, reason: null }))
    render(<OpenInButtons targets={['kicad', 'vscode', 'system']} onOpen={onOpen} />)

    expect(screen.getByRole('button', { name: 'Open in KiCad' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Open in editor' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Open' })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: 'Open in KiCad' }))
    expect(onOpen).toHaveBeenCalledWith('kicad')
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('shows the tool’s reason inline when it did not launch', async () => {
    const onOpen = vi.fn(async () => ({
      launched: false,
      tool: 'altium' as const,
      reason: 'Altium is not installed on this machine'
    }))
    render(<OpenInButtons targets={['altium']} onOpen={onOpen} />)

    await userEvent.click(screen.getByRole('button', { name: 'Open in Altium' }))
    expect(await screen.findByRole('note')).toHaveTextContent(
      'Altium is not installed on this machine'
    )
  })

  it('disables every button with the reason, never hiding them', () => {
    render(
      <OpenInButtons
        targets={['kicad', 'system']}
        disabledReason={COMPANION_OFFLINE_NOTE}
        onOpen={vi.fn(async () => null)}
      />
    )
    const kicad = screen.getByRole('button', { name: 'Open in KiCad' })
    expect(kicad).toBeDisabled()
    expect(kicad).toHaveAttribute('title', COMPANION_OFFLINE_NOTE)
    expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled()
  })

  it('renders nothing for no targets', () => {
    const { container } = render(<OpenInButtons targets={[]} onOpen={vi.fn(async () => null)} />)
    expect(container).toBeEmptyDOMElement()
  })
})
