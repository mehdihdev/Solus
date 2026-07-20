// Shared honest empty state for workspace screens whose live surfaces are
// future tickets (SOLUSDEV-152): title + what-will-appear body + optional
// status line and actions. No fabricated data, ever.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ScreenEmptyState } from './ScreenEmptyState'

describe('ScreenEmptyState', () => {
  it('renders the title and body', () => {
    render(<ScreenEmptyState title="Nothing here yet" body="Connect a source to populate this." />)
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument()
    expect(screen.getByText('Connect a source to populate this.')).toBeInTheDocument()
  })

  it('renders the mono status line when given', () => {
    render(<ScreenEmptyState title="T" body="B" status="NO DEVICE CONNECTED" />)
    expect(screen.getByText('NO DEVICE CONNECTED')).toBeInTheDocument()
  })

  it('omits the status line when not given', () => {
    render(<ScreenEmptyState title="T" body="B" />)
    expect(screen.queryByText('NO DEVICE CONNECTED')).not.toBeInTheDocument()
  })

  it('renders children as actions', () => {
    render(
      <ScreenEmptyState title="T" body="B">
        <button type="button">Do something</button>
      </ScreenEmptyState>
    )
    expect(screen.getByRole('button', { name: 'Do something' })).toBeInTheDocument()
  })
})
