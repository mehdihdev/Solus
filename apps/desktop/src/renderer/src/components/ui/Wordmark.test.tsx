import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Wordmark } from './Wordmark'

describe('Wordmark', () => {
  it('renders the SOLUS wordmark', () => {
    render(<Wordmark />)
    expect(screen.getByText('SOLUS')).toBeInTheDocument()
  })

  it('invokes onClick when provided', async () => {
    const onClick = vi.fn()
    render(<Wordmark onClick={onClick} />)
    await userEvent.click(screen.getByText('SOLUS'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})
