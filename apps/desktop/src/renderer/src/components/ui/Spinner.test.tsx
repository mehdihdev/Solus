import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Spinner } from './Spinner'

describe('Spinner', () => {
  it('exposes a loading status role', () => {
    render(<Spinner />)
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
  })
})
