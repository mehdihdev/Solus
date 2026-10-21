// The shared picker. Its whole job is to be item-agnostic: `mode` decides the
// shape, and the items supply their own copy. No provider id appears here.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SelectionPicker, type PickerPaging } from './SelectionPicker'
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

// Multi-select behaviour lives in MultiSelectPicker.test.tsx.

describe('SelectionPicker — sections (SOLUSDEV-216)', () => {
  const SECTIONS = [
    { header: 'From fsae-ev (team)', items: [{ id: 'o/vcu', name: 'o/vcu', subtitle: 'private' }] },
    {
      header: 'Your account · maya-k',
      items: [{ id: 'solus:account', name: 'Pick from my repositories' }]
    }
  ]

  it('renders one header per section with that section’s items beneath it', () => {
    render(<SelectionPicker items={[]} sections={SECTIONS} onSelect={vi.fn()} />)

    expect(screen.getByRole('group', { name: 'From fsae-ev (team)' })).toHaveTextContent('o/vcu')
    expect(screen.getByRole('group', { name: 'Your account · maya-k' })).toHaveTextContent(
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
        sections={[{ header: 'From fsae-ev (team)', items: [], notice: 'Suspended on GitHub' }]}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('Suspended on GitHub')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders section headers in natural case, uppercased by CSS', () => {
    render(<SelectionPicker items={[]} sections={SECTIONS} onSelect={vi.fn()} />)
    const header = screen.getByText('From fsae-ev (team)')
    expect(header).toHaveStyle({ textTransform: 'uppercase' })
    expect(header.textContent).toBe('From fsae-ev (team)')
  })

  describe('paging', () => {
    const paging = (over: Partial<PickerPaging> = {}): PickerPaging => ({
      query: '',
      onSearch: vi.fn(),
      shown: 1,
      total: 5,
      hasMore: true,
      busy: false,
      error: null,
      onLoadMore: vi.fn(),
      ...over
    })

    it('reports typed search text and the Load more click', async () => {
      const p = paging()
      render(<SelectionPicker items={[]} sections={SECTIONS} paging={p} onSelect={vi.fn()} />)
      await userEvent.type(screen.getByRole('searchbox', { name: 'Search repositories' }), 'v')
      expect(p.onSearch).toHaveBeenCalledWith('v')
      await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
      expect(p.onLoadMore).toHaveBeenCalledTimes(1)
      expect(screen.getByTestId('picker-showing')).toHaveTextContent('Showing 1 of 5')
    })

    it('hides the count and Load more when nothing more is available', () => {
      render(
        <SelectionPicker
          items={[]}
          sections={SECTIONS}
          paging={paging({ hasMore: false })}
          onSelect={vi.fn()}
        />
      )
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
      expect(screen.queryByTestId('picker-showing')).not.toBeInTheDocument()
    })

    it('disables Load more while busy and shows an error line', () => {
      render(
        <SelectionPicker
          items={[]}
          sections={SECTIONS}
          paging={paging({ busy: true, error: 'Nope' })}
          onSelect={vi.fn()}
        />
      )
      expect(screen.getByRole('button', { name: 'Load more' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent('Nope')
    })
  })
})
