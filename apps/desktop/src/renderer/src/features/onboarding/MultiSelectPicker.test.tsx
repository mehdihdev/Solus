// The multi-select picker, driven through the shared SelectionPicker entry. Two
// variants: CONNECT (first pick: search, select all shown, Track N / Skip) and
// EDIT (tracked pinned on top, adding/removing marks, diff, Save / Cancel).
import { describe, it, expect, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SelectionPicker } from './SelectionPicker'
import type { SelectableItem } from '../../lib/api/resources'

const DOCS: SelectableItem[] = [
  { id: 'docA', name: 'Rover chassis', subtitle: 'Maya' },
  { id: 'docB', name: 'Arm' },
  { id: 'docC', name: 'Gripper' }
]

function connect(over: Partial<Parameters<typeof SelectionPicker>[0]> = {}) {
  const onSelect = vi.fn()
  render(
    <SelectionPicker items={DOCS} mode="multi" label="document" onSelect={onSelect} {...over} />
  )
  return onSelect
}

describe('connect variant', () => {
  it('reports every ticked item', async () => {
    const onSelect = connect()
    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByLabelText('Gripper'))
    await userEvent.click(screen.getByRole('button', { name: 'Track 2 documents' }))
    expect(onSelect).toHaveBeenCalledWith([DOCS[0], DOCS[2]])
  })

  it('disables Track with a hint when nothing is picked; Skip reports an empty choice', async () => {
    const onSelect = connect()
    expect(screen.getByRole('button', { name: 'Track documents' })).toBeDisabled()
    expect(screen.getByText(/pick at least one, or skip/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    expect(onSelect).toHaveBeenCalledWith([])
  })

  it('shows an item’s own subtitle rather than invented copy', () => {
    connect()
    expect(screen.getByText('Maya')).toBeInTheDocument()
  })

  it('shows the most recently edited first, with its relative time', () => {
    const now = Date.now()
    const items: SelectableItem[] = [
      { id: 'old', name: 'Old', modified_at: new Date(now - 3 * 86_400_000).toISOString() },
      { id: 'new', name: 'New', modified_at: new Date(now - 2 * 3_600_000).toISOString() }
    ]
    connect({ items })
    const rows = screen.getAllByRole('checkbox', { name: /^(Old|New)$/ })
    expect(rows.map((r) => r.getAttribute('aria-label'))).toEqual(['New', 'Old'])
    expect(screen.getByText('2h ago')).toBeInTheDocument()
  })

  it('searches by name and keeps picks made outside the current view', async () => {
    const onSelect = connect()
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search documents' }), 'grip')
    expect(screen.queryByLabelText('Arm')).not.toBeInTheDocument()
    expect(screen.getByText(/1 selected not shown/i)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Gripper'))
    await userEvent.click(screen.getByRole('button', { name: 'Track 2 documents' }))
    expect(onSelect).toHaveBeenCalledWith([DOCS[1], DOCS[2]])
  })

  it('says so when a search matches nothing', async () => {
    connect()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search documents' }), 'zzz')
    expect(screen.getByText(/no documents match/i)).toBeInTheDocument()
  })

  it('selects all shown, then clears them; Clear empties everything', async () => {
    connect()
    await userEvent.click(screen.getByLabelText('Select all 3 shown'))
    expect(screen.getByRole('button', { name: 'Track 3 documents' })).toBeEnabled()
    await userEvent.click(screen.getByLabelText('Select all 3 shown'))
    expect(screen.getByRole('button', { name: 'Track documents' })).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.getByLabelText('Arm')).not.toBeChecked()
  })
})

describe('refresh', () => {
  it('refreshes explicitly, retains checked items, and does not select before Track', async () => {
    const fresh = { id: 'saved', name: 'FeatureScript MCP Workspace' }
    const onRefresh = vi.fn(async () => [...DOCS, fresh])
    const onSelect = connect({ onRefresh })
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: 'Refresh documents' }))
    expect(await screen.findByLabelText(fresh.name)).toBeInTheDocument()
    expect(screen.getByLabelText('Arm')).toBeChecked()
    expect(onSelect).not.toHaveBeenCalled()
    await userEvent.click(screen.getByLabelText(fresh.name))
    await userEvent.click(screen.getByRole('button', { name: 'Track 2 documents' }))
    expect(onSelect).toHaveBeenCalledWith([DOCS[1], fresh])
  })

  it('keeps the old listing and selection when refresh fails', async () => {
    connect({
      initial: ['docB'],
      onRefresh: vi.fn(async () => {
        throw new Error('quota')
      })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Refresh documents' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't refresh/i)
    expect(screen.getByLabelText('Arm')).toBeChecked()
  })

  it('blocks a second refresh and Track while one is pending', async () => {
    let finish!: (items: SelectableItem[]) => void
    const onRefresh = vi.fn(
      () =>
        new Promise<SelectableItem[]>((resolve) => {
          finish = resolve
        })
    )
    const onSelect = connect({ initial: ['docB'], onRefresh })
    await userEvent.click(screen.getByRole('button', { name: 'Refresh documents' }))
    expect(screen.getByRole('button', { name: 'Track 1 document' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Refreshing documents' })).toBeDisabled()
    expect(onRefresh).toHaveBeenCalledTimes(1)
    await act(async () => finish([]))
    expect(screen.getByRole('status')).toHaveTextContent(/no documents found/i)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('ignores a late refresh after the picker changes source', async () => {
    let finish!: (items: SelectableItem[]) => void
    const onRefresh = () =>
      new Promise<SelectableItem[]>((resolve) => {
        finish = resolve
      })
    const { rerender, unmount } = render(
      <SelectionPicker key="a" items={DOCS} mode="multi" label="document" onRefresh={onRefresh} />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Refresh documents' }))
    rerender(
      <SelectionPicker
        key="b"
        items={[{ id: 'b', name: 'Other source' }]}
        mode="multi"
        label="document"
      />
    )
    await act(async () => finish([{ id: 'late', name: 'Late old document' }]))
    expect(screen.queryByLabelText('Late old document')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Other source')).toBeInTheDocument()
    unmount()
  })
})

describe('edit variant', () => {
  function edit(initial: string[] = ['docB']) {
    const onSelect = vi.fn()
    const onCancel = vi.fn()
    render(
      <SelectionPicker
        items={DOCS}
        mode="multi"
        label="document"
        variant="edit"
        initial={initial}
        onSelect={onSelect}
        onCancel={onCancel}
      />
    )
    return { onSelect, onCancel }
  }

  it('pins what is tracked now above the other documents', () => {
    edit()
    const tracked = screen.getByRole('group', { name: /tracked now/i })
    expect(within(tracked).getByLabelText('Arm')).toBeChecked()
    const others = screen.getByRole('group', { name: /other documents/i })
    expect(within(others).getByLabelText('Rover chassis')).not.toBeChecked()
  })

  it('keeps Save disabled until something changes', () => {
    edit()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('marks additions and removals, warns about removals, and saves the new set', async () => {
    const { onSelect } = edit()
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByLabelText('Gripper'))
    expect(screen.getByText('Removing')).toBeInTheDocument()
    expect(screen.getByText('Adding')).toBeInTheDocument()
    expect(screen.getByText('+1 added')).toBeInTheDocument()
    expect(screen.getByText('−1 removed')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(/Arm/)
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onSelect).toHaveBeenCalledWith([DOCS[2]])
  })

  it('undoes a removal from the row', async () => {
    edit()
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: 'Undo removing Arm' }))
    expect(screen.getByLabelText('Arm')).toBeChecked()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('can stop tracking everything', async () => {
    const { onSelect } = edit(['docA', 'docB'])
    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onSelect).toHaveBeenCalledWith([])
  })

  it('cancels without reporting a selection', async () => {
    const { onSelect, onCancel } = edit()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
