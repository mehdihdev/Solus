import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Field } from './Field'

describe('Field', () => {
  it('emits typed characters via onChange', async () => {
    const onChange = vi.fn()
    render(<Field label="WORK EMAIL" value="" onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('WORK EMAIL'), 'a')
    expect(onChange).toHaveBeenCalledWith('a')
  })

  it('shows an error message and marks the input invalid', () => {
    render(<Field label="PASSWORD" value="x" onChange={() => {}} error="At least 8 characters" />)
    const input = screen.getByLabelText('PASSWORD')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('At least 8 characters')).toBeInTheDocument()
  })

  it('fires onSubmit when Enter is pressed', async () => {
    const onSubmit = vi.fn()
    render(<Field label="EMAIL" value="x" onChange={() => {}} onSubmit={onSubmit} />)
    await userEvent.type(screen.getByLabelText('EMAIL'), '{Enter}')
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})
