// SOLUSDEV-235 / EXT-12 — unreduced input never reaches the DOM.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ExtensionIcon } from './ExtensionIcon'
import { reduceSvg } from './svgReduce'

const GOOD =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 4h16" stroke="#fff"/></svg>'
const HOSTILE =
  '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script>' +
  '<path d="M0 0" fill="url(#x)"/></svg>'

describe('ExtensionIcon', () => {
  it('renders exactly the reducer output for an acceptable icon', () => {
    const { container } = render(<ExtensionIcon svg={GOOD} label="BOM" size={20} />)
    const icon = screen.getByRole('img', { name: 'BOM' })
    // Compare through the same serializer: the DOM re-emits `<path/>` as `<path></path>`.
    const expected = document.createElement('span')
    expected.innerHTML = reduceSvg(GOOD)!
    expect(icon.innerHTML).toBe(expected.innerHTML)
    expect(container.innerHTML).toContain('stroke="currentColor"')
    expect(container.innerHTML).not.toContain('#fff')
    expect(icon).toHaveStyle({ width: '20px', height: '20px' })
  })

  it('renders a neutral fallback — none of the original bytes — for a hostile icon', () => {
    const { container } = render(<ExtensionIcon svg={HOSTILE} />)
    expect(screen.getByTestId('extension-icon-fallback')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.innerHTML).not.toContain('onload')
    expect(container.innerHTML).not.toContain('alert')
  })

  it('renders the fallback for a missing icon', () => {
    render(<ExtensionIcon svg={null} />)
    expect(screen.getByTestId('extension-icon-fallback')).toBeInTheDocument()
  })

  it('is decorative without a label', () => {
    render(<ExtensionIcon svg={GOOD} />)
    expect(screen.getByTestId('extension-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
