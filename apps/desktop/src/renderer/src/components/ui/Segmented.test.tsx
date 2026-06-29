import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Segmented } from './Segmented'

describe('Segmented', () => {
  it('marks the active option as checked', () => {
    render(<Segmented options={['Guide', 'Expert'] as const} value="Guide" onChange={() => {}} />)
    expect(screen.getByRole('radio', { name: 'Guide' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Expert' })).toHaveAttribute('aria-checked', 'false')
  })

  it('emits the selected option on click', async () => {
    const onChange = vi.fn()
    render(<Segmented options={['Guide', 'Expert'] as const} value="Guide" onChange={onChange} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(onChange).toHaveBeenCalledWith('Expert')
  })
})
