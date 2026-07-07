import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Avatar } from './Avatar'

describe('Avatar', () => {
  it('renders two-letter initials from the name', () => {
    render(<Avatar name="Maya Krishnan" />)
    expect(screen.getByText('MK')).toBeInTheDocument()
  })

  it('handles single-word names', () => {
    render(<Avatar name="Priya" />)
    expect(screen.getByText('P')).toBeInTheDocument()
  })
})
