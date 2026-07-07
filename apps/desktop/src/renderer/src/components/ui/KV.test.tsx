import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { KV } from './KV'

describe('KV', () => {
  it('renders key and value', () => {
    render(<KV k="Ratio" v="9:1" />)
    expect(screen.getByText('Ratio')).toBeInTheDocument()
    expect(screen.getByText('9:1')).toBeInTheDocument()
  })
})
