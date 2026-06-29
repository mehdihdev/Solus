import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Card } from './Card'

describe('Card', () => {
  it('renders children', () => {
    render(<Card>inside</Card>)
    expect(screen.getByText('inside')).toBeInTheDocument()
  })

  it('invokes onClick when clicked', async () => {
    const onClick = vi.fn()
    render(<Card onClick={onClick}>clickable</Card>)
    await userEvent.click(screen.getByText('clickable'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})
