// SOLUSDEV-233: the Solus brand logo — inline SVG whose colors ride the
// runtime design tokens, so it re-skins with the theme/accent chosen in
// Settings. The SOL surfaces keep the SolOrb.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SolusLogo } from './SolusLogo'

describe('SolusLogo', () => {
  it('renders the mark as an accessible, sized image', () => {
    render(<SolusLogo size={24} />)
    const svg = screen.getByRole('img', { name: 'Solus' })
    expect(svg).toHaveAttribute('width', '24')
    expect(svg).toHaveAttribute('height', '24')
  })

  it('drives every color from theme tokens, never hardcoded brand hex', () => {
    const { container } = render(<SolusLogo />)
    const styles = Array.from(container.querySelectorAll('rect, path')).map(
      (el) => el.getAttribute('style') ?? ''
    )
    expect(styles.length).toBeGreaterThan(0)
    // The connector and rings follow the ACCENT token; surfaces follow the
    // theme tokens — switching theme/accent in Settings re-skins the mark.
    expect(styles.join(' ')).toContain('var(--acc)')
    expect(styles.join(' ')).toContain('var(--sur2)')
    for (const style of styles) {
      expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}/)
    }
  })
})
