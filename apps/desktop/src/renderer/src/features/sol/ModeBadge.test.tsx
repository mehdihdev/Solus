// SOLUSDEV-252 S3: the Guide | Build badge — labels the SOLX-01 axis, click toggles.
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModeBadge } from './ModeBadge'

describe('ModeBadge', () => {
  it('labels guide/do as Guide/Build and asks for the opposite on click', () => {
    const onChange = vi.fn()
    const { rerender } = render(<ModeBadge mode="guide" onChange={onChange} />)
    const badge = screen.getByRole('button', { name: 'SOL action mode' })
    expect(badge).toHaveTextContent('Guide')
    fireEvent.click(badge)
    expect(onChange).toHaveBeenCalledWith('do')
    rerender(<ModeBadge mode="do" onChange={onChange} />)
    expect(badge).toHaveTextContent('Build')
    fireEvent.click(badge)
    expect(onChange).toHaveBeenLastCalledWith('guide')
  })
})
