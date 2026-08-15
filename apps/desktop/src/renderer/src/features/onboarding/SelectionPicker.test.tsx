// The shared picker. Its whole job is to be item-agnostic: `mode` decides the
// shape, and the items supply their own copy. No provider id appears here.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SelectionPicker } from './SelectionPicker'
import type { SelectableItem } from '../../lib/api/resources'

const DOCS: SelectableItem[] = [
  { id: 'docA', name: 'Rover chassis', subtitle: 'Maya' },
  { id: 'docB', name: 'Arm' },
  { id: 'docC', name: 'Gripper' }
]

describe('SelectionPicker — single', () => {
  it('reports the one chosen item', async () => {
    const onSelect = vi.fn()
    render(<SelectionPicker items={DOCS} mode="single" onSelect={onSelect} />)

    await userEvent.selectOptions(screen.getByLabelText('Choose an item to track'), 'docB')

    expect(onSelect).toHaveBeenCalledWith([DOCS[1]])
  })
})

describe('SelectionPicker — multi', () => {
  it('reports every ticked item', async () => {
    const onSelect = vi.fn()
    render(<SelectionPicker items={DOCS} mode="multi" onSelect={onSelect} />)

    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByLabelText('Gripper'))
    await userEvent.click(screen.getByRole('button', { name: /track 2/i }))

    expect(onSelect).toHaveBeenCalledWith([DOCS[0], DOCS[2]])
  })

  it('allows confirming an empty selection — connected but tracking nothing', async () => {
    const onSelect = vi.fn()
    render(<SelectionPicker items={DOCS} mode="multi" onSelect={onSelect} />)

    await userEvent.click(screen.getByRole('button', { name: /track none/i }))

    expect(onSelect).toHaveBeenCalledWith([])
  })

  it('starts from the currently tracked items when editing an existing selection', async () => {
    const onSelect = vi.fn()
    render(<SelectionPicker items={DOCS} mode="multi" initial={['docB']} onSelect={onSelect} />)

    expect(screen.getByLabelText('Arm')).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: /track 1/i }))

    expect(onSelect).toHaveBeenCalledWith([DOCS[1]])
  })

  it('shows an item’s own subtitle rather than invented copy', () => {
    render(<SelectionPicker items={DOCS} mode="multi" />)
    expect(screen.getByText('Maya')).toBeInTheDocument()
  })
})
