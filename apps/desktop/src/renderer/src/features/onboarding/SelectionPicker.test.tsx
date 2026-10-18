// The shared picker. Its whole job is to be item-agnostic: `mode` decides the
// shape, and the items supply their own copy. No provider id appears here.
import { describe, it, expect, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
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

it('refreshes explicitly, retains checked items, and does not select before Track', async () => {
  const fresh = { id: 'saved', name: 'FeatureScript MCP Workspace' }
  const onRefresh = vi.fn(async () => [...DOCS, fresh])
  const onSelect = vi.fn()
  render(<SelectionPicker items={DOCS} mode="multi" onRefresh={onRefresh} onSelect={onSelect} />)
  await userEvent.click(screen.getByLabelText('Arm'))
  await userEvent.click(screen.getByRole('button', { name: /refresh/i }))
  expect(await screen.findByLabelText(fresh.name)).toBeInTheDocument()
  expect(screen.getByLabelText('Arm')).toBeChecked()
  expect(onRefresh).toHaveBeenCalledTimes(1)
  expect(onSelect).not.toHaveBeenCalled()
  await userEvent.click(screen.getByLabelText(fresh.name))
  await userEvent.click(screen.getByRole('button', { name: /track 2/i }))
  expect(onSelect).toHaveBeenCalledWith([DOCS[1], fresh])
})

it('keeps the old listing and selection when refresh fails', async () => {
  render(
    <SelectionPicker
      items={DOCS}
      mode="multi"
      initial={['docB']}
      onRefresh={vi.fn(async () => {
        throw new Error('quota')
      })}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: /refresh/i }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/refresh/i)
  expect(screen.getByLabelText('Arm')).toBeChecked()
})

it('prevents concurrent refresh and Track while the request is pending', async () => {
  let finish!: (items: SelectableItem[]) => void
  const onRefresh = vi.fn(
    () =>
      new Promise<SelectableItem[]>((resolve) => {
        finish = resolve
      })
  )
  const onSelect = vi.fn()
  render(
    <SelectionPicker
      items={DOCS}
      mode="multi"
      initial={['docB']}
      onRefresh={onRefresh}
      onSelect={onSelect}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: /refresh/i }))
  expect(screen.getByRole('button', { name: /track 1/i })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: /refreshing/i }))
  expect(onRefresh).toHaveBeenCalledTimes(1)
  expect(onSelect).not.toHaveBeenCalled()
  await act(async () => finish([]))
  expect(screen.getByRole('status')).toHaveTextContent('No items found')
  expect(screen.getByRole('button', { name: /track none/i })).toBeEnabled()
})

it('ignores a late refresh after the picker closes or changes source', async () => {
  let finish!: (items: SelectableItem[]) => void
  const onRefresh = () =>
    new Promise<SelectableItem[]>((resolve) => {
      finish = resolve
    })
  const { rerender, unmount } = render(
    <SelectionPicker key="source-a" items={DOCS} mode="multi" onRefresh={onRefresh} />
  )
  await userEvent.click(screen.getByRole('button', { name: /refresh/i }))
  rerender(
    <SelectionPicker key="source-b" items={[{ id: 'b', name: 'Other source' }]} mode="multi" />
  )
  await act(async () => finish([{ id: 'late', name: 'Late old document' }]))
  expect(screen.queryByLabelText('Late old document')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Other source')).toBeInTheDocument()
  unmount()
})

describe('SelectionPicker — sections (SOLUSDEV-216)', () => {
  const SECTIONS = [
    { header: 'FROM FSAE-EV (TEAM)', items: [{ id: 'o/vcu', name: 'o/vcu', subtitle: 'private' }] },
    {
      header: 'YOUR ACCOUNT · maya-k',
      items: [{ id: 'solus:account', name: 'Pick from my repositories' }]
    }
  ]

  it('renders one header per section with that section’s items beneath it', () => {
    render(<SelectionPicker items={[]} sections={SECTIONS} onSelect={vi.fn()} />)

    expect(screen.getByRole('group', { name: 'FROM FSAE-EV (TEAM)' })).toHaveTextContent('o/vcu')
    expect(screen.getByRole('group', { name: 'YOUR ACCOUNT · maya-k' })).toHaveTextContent(
      'Pick from my repositories'
    )
    expect(screen.getByText('private')).toBeInTheDocument()
    expect(screen.queryByText('No items found.')).not.toBeInTheDocument()
  })

  it('reports the clicked item as the single choice', async () => {
    const onSelect = vi.fn()
    render(<SelectionPicker items={[]} sections={SECTIONS} onSelect={onSelect} />)

    await userEvent.click(screen.getByRole('button', { name: /o\/vcu/ }))

    expect(onSelect).toHaveBeenCalledWith([SECTIONS[0].items[0]])
  })

  it('shows a section notice and no items for a suspended section', () => {
    render(
      <SelectionPicker
        items={[]}
        sections={[{ header: 'FROM FSAE-EV (TEAM)', items: [], notice: 'Suspended on GitHub' }]}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('Suspended on GitHub')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
