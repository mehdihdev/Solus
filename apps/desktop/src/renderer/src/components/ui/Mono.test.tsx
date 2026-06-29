import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Mono } from './Mono'

describe('Mono', () => {
  it('renders its text content', () => {
    render(<Mono>starting point</Mono>)
    expect(screen.getByText('starting point')).toBeInTheDocument()
  })
})
