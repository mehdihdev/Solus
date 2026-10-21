import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CommandPalette, type CommandPaletteProps } from './CommandPalette'
import type { PaletteItem } from './paletteItems'

const ITEMS: PaletteItem[] = [
  { key: 'page:home', kind: 'page', label: 'Home', target: { type: 'screen', screen: 'home' } },
  {
    key: 'page:bench',
    kind: 'page',
    label: 'Live Bench',
    keywords: ['telemetry'],
    target: { type: 'screen', screen: 'bench' }
  },
  {
    key: 'project:p1',
    kind: 'project',
    label: 'Mars Rover',
    detail: 'Rover Lab',
    target: { type: 'project', project: { id: 'p1', name: 'Mars Rover', teamId: 't1' } }
  },
  { key: 'team:t1', kind: 'team', label: 'Rover Lab', target: { type: 'team', teamId: 't1' } },
  {
    key: 'node:p1:e1',
    kind: 'node',
    label: 'IMU <b>bold</b>',
    detail: 'ee · sensor',
    target: { type: 'node', projectId: 'p1', entityId: 'e1' }
  }
]

function setup(over: Partial<CommandPaletteProps> = {}): {
  props: CommandPaletteProps
  input: HTMLElement
} {
  const props: CommandPaletteProps = {
    items: ITEMS,
    recentKeys: [],
    loading: false,
    hasProject: true,
    onPick: vi.fn(),
    onClose: vi.fn(),
    ...over
  }
  render(<CommandPalette {...props} />)
  return { props, input: screen.getByRole('combobox', { name: 'Search Solus' }) }
}

const optionLabels = (): (string | null)[] =>
  screen.queryAllByRole('option').map((o) => o.getAttribute('data-key'))

describe('CommandPalette', () => {
  it('opens as a modal dialog with the search field focused', () => {
    const { input } = setup()
    expect(screen.getByRole('dialog', { name: 'Search' })).toHaveAttribute('aria-modal', 'true')
    expect(input).toHaveFocus()
  })

  it('shows pages, projects and teams for an empty query, with recents first', () => {
    setup({ recentKeys: ['team:t1'] })
    expect(screen.getByText('Recents')).toBeInTheDocument()
    expect(optionLabels()).toEqual(['team:t1', 'page:home', 'page:bench', 'project:p1', 'team:t1'])
  })

  it('ranks rows after a Recents section by their real position (one highlight, true rank)', () => {
    const { input, props } = setup({ recentKeys: ['team:t1'] })
    const selected = (): string[] =>
      screen
        .getAllByRole('option')
        .filter((o) => o.getAttribute('aria-selected') === 'true')
        .map((o) => o.id)
    expect(selected()).toEqual(['palette-option-recent-team:t1'])
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(selected()).toEqual(['palette-option-team:t1'])
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(props.onPick).toHaveBeenLastCalledWith(ITEMS[3], 4, '')
    fireEvent.click(screen.getByText('Home'))
    expect(props.onPick).toHaveBeenLastCalledWith(ITEMS[0], 1, '')
  })

  it('restores focus to whatever opened it when it closes', () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const { unmount } = render(
      <CommandPalette
        items={ITEMS}
        recentKeys={[]}
        loading={false}
        hasProject
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(opener).not.toHaveFocus()
    unmount()
    expect(opener).toHaveFocus()
    opener.remove()
  })

  it('filters as you type, nodes included', () => {
    const { input } = setup()
    fireEvent.change(input, { target: { value: 'imu' } })
    expect(optionLabels()).toEqual(['node:p1:e1'])
  })

  it('renders ingested node names as text, never markup', () => {
    const { input } = setup()
    fireEvent.change(input, { target: { value: 'imu' } })
    expect(screen.getByText('IMU <b>bold</b>')).toBeInTheDocument()
    expect(document.querySelector('[role="option"] b')).toBeNull()
  })

  it('walks results with the arrow keys and opens with Enter, reporting the rank', () => {
    const { input, props } = setup()
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input).toHaveAttribute('aria-activedescendant', 'palette-option-page:bench')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(props.onPick).toHaveBeenCalledWith(ITEMS[1], 1, '')
  })

  it('wraps the selection at both ends', () => {
    const { input } = setup()
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input).toHaveAttribute('aria-activedescendant', 'palette-option-team:t1')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input).toHaveAttribute('aria-activedescendant', 'palette-option-page:home')
  })

  it('opens a result on click', () => {
    const { props } = setup()
    fireEvent.click(screen.getByText('Mars Rover'))
    expect(props.onPick).toHaveBeenCalledWith(ITEMS[2], 2, '')
  })

  it('cycles the type filter with Tab and Shift+Tab', () => {
    const { input } = setup()
    fireEvent.keyDown(input, { key: 'Tab' })
    expect(screen.getByRole('tab', { name: 'Pages' })).toHaveAttribute('aria-selected', 'true')
    expect(optionLabels()).toEqual(['page:home', 'page:bench'])
    fireEvent.keyDown(input, { key: 'Tab', shiftKey: true })
    fireEvent.keyDown(input, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('tab', { name: 'Nodes' })).toHaveAttribute('aria-selected', 'true')
    expect(optionLabels()).toEqual(['node:p1:e1'])
  })

  it('switches the filter by clicking a tab and resets the selection', () => {
    setup()
    fireEvent.click(screen.getByRole('tab', { name: 'Projects' }))
    expect(optionLabels()).toEqual(['project:p1'])
    expect(screen.getByRole('option')).toHaveAttribute('aria-selected', 'true')
  })

  it('closes on Escape, the close button and a backdrop click — not a click inside', () => {
    const { input, props } = setup()
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Close search' }))
    fireEvent.mouseDown(screen.getByTestId('palette-backdrop'))
    fireEvent.mouseDown(input)
    expect(props.onClose).toHaveBeenCalledTimes(3)
  })

  it('says so when nothing matches', () => {
    const { input } = setup()
    fireEvent.change(input, { target: { value: 'zzz' } })
    expect(screen.getByText('No results for “zzz”')).toBeInTheDocument()
  })

  it('asks for a project before searching nodes', () => {
    setup({ hasProject: false, items: ITEMS.filter((i) => i.kind !== 'node') })
    fireEvent.click(screen.getByRole('tab', { name: 'Nodes' }))
    expect(screen.getByText('Open a project to search its nodes.')).toBeInTheDocument()
  })

  it('shows a quiet loading line while projects or nodes are still arriving', () => {
    setup({ loading: true })
    expect(screen.getByRole('status')).toHaveTextContent('Loading…')
  })
})
