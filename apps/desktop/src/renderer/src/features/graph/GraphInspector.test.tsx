// Inspector rail of the Context Model screen (SOLUSDEV-152): the prototype
// node detail is gone; the rail honestly explains what will appear here once
// the graph has entities.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GraphInspector } from './GraphInspector'

describe('GraphInspector', () => {
  it('explains what the inspector will show', () => {
    render(<GraphInspector />)
    expect(screen.getByText(/properties, sources, and links across domains/i)).toBeInTheDocument()
  })

  it('contains no fabricated node data or tool buttons', () => {
    const { container } = render(<GraphInspector />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/DRV8316C|leg_ik\.c|Open in KiCad|Ask SOL/)
    expect(text).not.toMatch(/CONNECTED ACROSS DOMAINS/)
  })
})
