import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import { useSettingsStore } from '../../../store/settingsStore'
import { HelpPopover } from './HelpPopover'

const node = (id: string): Entity => ({
  id,
  type: 'part',
  name: id,
  domain: 'mechanical',
  source_key: id
})
const open = () => fireEvent.click(screen.getByRole('button', { name: 'Help' }))

beforeEach(() => useSettingsStore.setState({ solMode: 'Guide' }))

describe('HelpPopover', () => {
  it('opens a dialog with the navigation instructions and the current trail', () => {
    render(<HelpPopover trail={[node('A'), node('B')]} onOverview={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
    open()
    const dialog = screen.getByRole('dialog', { name: 'Workspace help' })
    expect(dialog).toHaveTextContent(
      'Hover a card and scroll in to open it · scroll out to go back'
    )
    expect(dialog).toHaveTextContent('Double-click or → enters · ← goes back · Escape clears')
    expect(dialog).toHaveTextContent('Drag a card anywhere; positions are shared with your team')
    expect(dialog).toHaveTextContent('Add (top-left) brings in integrations and hardware')
    expect(dialog).toHaveTextContent('Project › A › B')
  })

  it('offers Project overview, disabled at the root, and closes after using it', () => {
    const onOverview = vi.fn()
    const { rerender } = render(<HelpPopover trail={[]} onOverview={onOverview} />)
    open()
    expect(screen.getByRole('button', { name: 'Project overview' })).toBeDisabled()
    expect(screen.getByRole('dialog')).toHaveTextContent('Project')
    rerender(<HelpPopover trail={[node('A')]} onOverview={onOverview} />)
    fireEvent.click(screen.getByRole('button', { name: 'Project overview' }))
    expect(onOverview).toHaveBeenCalledOnce()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('closes on Escape, on an outside click and on its × button', () => {
    render(<HelpPopover trail={[]} onOverview={vi.fn()} />)
    open()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    open()
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('dialog')).toBeNull()
    open()
    fireEvent.pointerDown(screen.getByRole('dialog'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close help' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('uses terse Expert copy', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<HelpPopover trail={[]} onOverview={vi.fn()} />)
    open()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Scroll in opens · scroll out goes back')
    expect(dialog).not.toHaveTextContent('Hover a card')
  })
})
