// SOLUSDEV-235 — the Store card and its badges.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AvailabilityPill, ExtensionCard, PublisherBadge } from './ExtensionCard'
import { EXTENSION_CATALOG } from './extensions.catalog'
import { buildView, DEFAULT_INSTALL_STATE } from './extensionLogic'
import type { ExtensionView } from './extension.types'

function viewOf(id: string, installed: boolean, connected: string[] = []): ExtensionView {
  const manifest = EXTENSION_CATALOG.find((m) => m.id === id)!
  return buildView(manifest, { ...DEFAULT_INSTALL_STATE, installed }, new Set(connected as never[]))
}

describe('PublisherBadge', () => {
  it('marks Solus extensions verified and community ones plainly', () => {
    const { rerender } = render(<PublisherBadge publisher="solus" />)
    expect(screen.getByText('SOLUS')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Verified by Solus' })).toBeInTheDocument()
    rerender(<PublisherBadge publisher="community" />)
    expect(screen.getByText('COMMUNITY')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Verified by Solus' })).not.toBeInTheDocument()
  })
})

describe('AvailabilityPill', () => {
  it('reads INSTALLED, NEEDS <source>, or AVAILABLE', () => {
    const { rerender } = render(<AvailabilityPill view={viewOf('experiments', true)} />)
    expect(screen.getByText('INSTALLED')).toBeInTheDocument()
    rerender(<AvailabilityPill view={viewOf('fsae-rules-checker', false)} />)
    expect(screen.getByText('NEEDS CAD|EDA')).toBeInTheDocument()
    rerender(<AvailabilityPill view={viewOf('bom', false, ['eda'])} />)
    expect(screen.getByText('AVAILABLE')).toBeInTheDocument()
  })
})

describe('ExtensionCard', () => {
  it('renders name, publisher, summary and status, and opens on click', async () => {
    const onOpen = vi.fn()
    render(<ExtensionCard view={viewOf('bom', false)} layout="grid" onOpen={onOpen} />)
    expect(screen.getByText('BOM')).toBeInTheDocument()
    expect(screen.getByText(/Bill of materials/)).toBeInTheDocument()
    expect(screen.getByText('NEEDS EDA')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open BOM' }))
    expect(onOpen).toHaveBeenCalledWith('bom')
  })

  it('is keyboard-operable', async () => {
    const onOpen = vi.fn()
    render(<ExtensionCard view={viewOf('scene', true)} layout="list" onOpen={onOpen} />)
    screen.getByRole('button', { name: 'Open Scene' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onOpen).toHaveBeenCalledWith('scene')
  })
})
