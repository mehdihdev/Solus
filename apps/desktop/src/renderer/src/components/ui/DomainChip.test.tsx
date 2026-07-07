import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DomainChip } from './DomainChip'

describe('DomainChip', () => {
  it('renders the domain label', () => {
    render(<DomainChip d="ee" />)
    expect(screen.getByText('ELECTRICAL')).toBeInTheDocument()
  })

  it('fires onClick when interactive', async () => {
    const onClick = vi.fn()
    render(<DomainChip d="sw" onClick={onClick} />)
    await userEvent.click(screen.getByText('SOFTWARE'))
    expect(onClick).toHaveBeenCalled()
  })
})
