// SOLUSDEV-233: the Solus brand logo (assets/solus-logo.svg) — replaces the
// orb in brand positions; the SOL page and mini-orb keep the SolOrb.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SolusLogo } from './SolusLogo'

describe('SolusLogo', () => {
  it('renders the bundled logo as an accessible image', () => {
    render(<SolusLogo size={24} />)
    const img = screen.getByRole('img', { name: 'Solus' })
    // Vite inlines small SVGs as data: URIs — assert the bundled mark, not a path.
    expect(img.getAttribute('src')).toMatch(/^data:image\/svg\+xml|solus-logo/)
    expect(img).toHaveStyle({ width: '24px', height: '24px' })
  })
})
