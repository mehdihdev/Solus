// SOLUSDEV-235 — the on/off switch primitive.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Switch } from './Switch'

describe('Switch', () => {
  it('is an accessible switch reflecting its checked state', () => {
    render(<Switch checked ariaLabel="Enable" onChange={vi.fn()} />)
    expect(screen.getByRole('switch', { name: 'Enable' })).toHaveAttribute('aria-checked', 'true')
  })

  it('reports the flipped value on click', async () => {
    const onChange = vi.fn()
    render(<Switch checked={false} ariaLabel="Enable" onChange={onChange} />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('does nothing while disabled', async () => {
    const onChange = vi.fn()
    render(<Switch checked disabled ariaLabel="Enable" onChange={onChange} />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('switch')).toBeDisabled()
  })
})
