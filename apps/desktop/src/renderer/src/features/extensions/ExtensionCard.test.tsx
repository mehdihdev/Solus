// SOLUSDEV-235 — the Store card and its badges, over server-sourced views.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AvailabilityPill, ExtensionCard, PublisherBadge } from './ExtensionCard'
import { manifest, viewOf } from './testing/fixtures'

describe('PublisherBadge', () => {
  it('marks verified publishers by name with the check, others as COMMUNITY', () => {
    const { rerender } = render(<PublisherBadge publisher="Solus" verified />)
    expect(screen.getByText('Solus')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Verified by Solus' })).toBeInTheDocument()
    rerender(<PublisherBadge publisher="Jane" verified={false} />)
    expect(screen.getByText('COMMUNITY')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Verified by Solus' })).not.toBeInTheDocument()
  })
})

describe('AvailabilityPill', () => {
  it('reads INSTALLED, NEEDS <source>, AVAILABLE or BLOCKED', () => {
    const { rerender } = render(<AvailabilityPill view={viewOf({ install: {} })} />)
    expect(screen.getByText('INSTALLED')).toBeInTheDocument()
    rerender(
      <AvailabilityPill
        view={viewOf({
          manifest: manifest({
            extension: { ...manifest().extension, requires: [['cad', 'eda']] }
          })
        })}
      />
    )
    expect(screen.getByText('NEEDS CAD|EDA')).toBeInTheDocument()
    rerender(<AvailabilityPill view={viewOf({ connected: ['eda'] })} />)
    expect(screen.getByText('AVAILABLE')).toBeInTheDocument()
    rerender(<AvailabilityPill view={viewOf({ blocked: true })} />)
    expect(screen.getByText('BLOCKED')).toBeInTheDocument()
  })

  it('flags an available update on an installed extension', () => {
    render(
      <AvailabilityPill
        view={viewOf({
          install: { update_available: { version: '1.3.0', widens_permissions: false } }
        })}
      />
    )
    expect(screen.getByTitle('Update available: 1.3.0')).toBeInTheDocument()
  })
})

describe('ExtensionCard', () => {
  it('renders name, publisher, summary and status, and opens on click', async () => {
    const onOpen = vi.fn()
    render(<ExtensionCard view={viewOf()} layout="grid" onOpen={onOpen} />)
    expect(screen.getByText('BOM')).toBeInTheDocument()
    expect(screen.getByText(/Bill of materials/)).toBeInTheDocument()
    expect(screen.getByText('NEEDS EDA')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open BOM' }))
    expect(onOpen).toHaveBeenCalledWith('bom')
  })

  it('is keyboard-operable', async () => {
    const onOpen = vi.fn()
    render(<ExtensionCard view={viewOf({ install: {} })} layout="list" onOpen={onOpen} />)
    screen.getByRole('button', { name: 'Open BOM' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onOpen).toHaveBeenCalledWith('bom')
  })
})
