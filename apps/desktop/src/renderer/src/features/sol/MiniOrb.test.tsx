import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MiniOrb } from './MiniOrb'

describe('MiniOrb', () => {
  it('renders nothing when hidden', () => {
    const { container } = render(<MiniOrb hidden onClick={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the corner orb and fires onClick', () => {
    const onClick = vi.fn()
    render(<MiniOrb hidden={false} onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
