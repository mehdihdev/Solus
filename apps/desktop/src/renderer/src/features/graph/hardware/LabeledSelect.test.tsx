import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LabeledSelect } from './LabeledSelect'

const options = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' }
] as const

it('renders a labelled select and reports the chosen value', async () => {
  const onChange = vi.fn()
  render(<LabeledSelect label="Robot" value="a" options={options} onChange={onChange} />)
  const select = screen.getByRole('combobox', { name: 'Robot' })
  expect(select).toHaveValue('a')
  await userEvent.selectOptions(select, 'b')
  expect(onChange).toHaveBeenCalledExactlyOnceWith('b')
})

it('can be disabled', () => {
  render(<LabeledSelect label="Robot" value="a" options={options} onChange={vi.fn()} disabled />)
  expect(screen.getByRole('combobox', { name: 'Robot' })).toBeDisabled()
})
