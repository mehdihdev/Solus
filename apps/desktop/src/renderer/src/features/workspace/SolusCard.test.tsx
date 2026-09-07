import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { SolusEntry, SolusSection } from '../../lib/api/resources'
import { emptySections, type SolusState } from '../graph/useSolusConfig'

const state = vi.hoisted(() => ({ current: null as unknown }))
const actions = vi.hoisted(() => ({
  importFile: vi.fn(async () => undefined),
  submit: vi.fn(async () => true),
  remove: vi.fn(async () => true)
}))

vi.mock('../graph/useSolusConfig', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../graph/useSolusConfig')>()),
  useSolusConfig: () => state.current
}))
vi.mock('../graph/solusActions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../graph/solusActions')>()),
  useSolusActions: () => actions
}))

import { SolusCard } from './SolusCard'

function entry(over: Partial<SolusEntry> & { id: string; section: SolusSection }): SolusEntry {
  return {
    kind: 'text',
    author: 'user',
    text: 'Battery is 6S; never charge above 25.2 V',
    name: null,
    artifact_id: null,
    entity_id: `e-${over.id}`,
    media_type: null,
    size_bytes: null,
    created_by: 'u1',
    created_at: '2026-09-07T10:00:00Z',
    updated_at: '2026-09-07T10:00:00Z',
    ...over
  }
}

function ready(entries: SolusEntry[] = []): SolusState {
  const sections = emptySections()
  for (const e of entries) sections[e.section].push(e)
  return { status: 'ready', entityId: 'solus-1', sections, refetch: vi.fn(async () => null) }
}

const row = (label: string): HTMLElement => screen.getByRole('button', { name: new RegExp(label) })

describe('SolusCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.current = ready()
  })

  it('asks for a project when none is open, and is honest when offline', () => {
    const { unmount } = render(<SolusCard projectId={null} projectName={null} />)
    expect(screen.getByText(/Open or switch to a project/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Hardware configs/ })).toBeNull()
    unmount()
    state.current = { ...ready(), status: 'offline' }
    render(<SolusCard projectId="p1" projectName="Rover" />)
    expect(screen.getByRole('note')).toHaveTextContent("can't reach its API")
  })

  it('lists the five sections with honest counts and opens one in place', async () => {
    state.current = ready([
      entry({ id: 'a', section: 'errors', author: 'sol', text: 'pytest exited 1' }),
      entry({ id: 'b', section: 'details' })
    ])
    render(<SolusCard projectId="p1" projectName="Rover" />)
    expect(screen.getByText('.SOLUS')).toBeInTheDocument()
    expect(screen.getByText('Rover')).toBeInTheDocument()
    for (const label of [
      'Hardware configs',
      'Project details',
      'Error logging',
      'Documentation',
      'Code environment'
    ]) {
      expect(row(label)).toHaveAttribute('aria-expanded', 'false')
    }
    expect(row('Error logging')).toHaveTextContent('AUTO + YOU')
    expect(screen.queryByText('pytest exited 1')).toBeNull()
    await userEvent.click(row('Error logging'))
    expect(row('Error logging')).toHaveAttribute('aria-expanded', 'true')
    const panel = screen.getByTestId('solus-entry-a')
    expect(panel).toHaveTextContent('pytest exited 1')
    expect(panel).toHaveTextContent('filed by SOL')
    // An empty section says so instead of inventing a row.
    await userEvent.click(row('Hardware configs'))
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
  })

  it('adds a note through the shared composer and actions', async () => {
    render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Project details'))
    await userEvent.click(screen.getByRole('button', { name: 'Add a note' }))
    await userEvent.type(screen.getByRole('textbox'), 'Wheelbase 1.6 m')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(actions.submit).toHaveBeenCalledWith(
      { section: 'details', kind: 'type' },
      'Wheelbase 1.6 m'
    )
    // The composer closes once the action reports success.
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('edits a note in place, prefilled', async () => {
    const note = entry({ id: 'n1', section: 'docs', text: 'old text' })
    state.current = ready([note])
    render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Documentation'))
    await userEvent.click(within(screen.getByTestId('solus-entry-n1')).getByText('Edit'))
    const box = screen.getByRole('textbox')
    expect(box).toHaveValue('old text')
    await userEvent.clear(box)
    await userEvent.type(box, 'new text')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(actions.submit).toHaveBeenCalledWith(
      { section: 'docs', kind: 'edit', entry: note },
      'new text'
    )
  })

  it('deletes only on the second, confirming click', async () => {
    const file = entry({
      id: 'f1',
      section: 'hardware',
      kind: 'artifact',
      text: null,
      name: 'rules.pdf',
      media_type: 'application/pdf',
      size_bytes: 2048
    })
    state.current = ready([file])
    render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Hardware configs'))
    const card = screen.getByTestId('solus-entry-f1')
    expect(card).toHaveTextContent('rules.pdf')
    expect(card).toHaveTextContent('application/pdf')
    expect(within(card).queryByText('Edit')).toBeNull() // files are not editable text
    const now = vi.spyOn(Date, 'now')
    now.mockReturnValue(1_000)
    await userEvent.click(within(card).getByRole('button', { name: 'Delete rules.pdf' }))
    expect(actions.remove).not.toHaveBeenCalled()
    // A confirm inside the dwell window is a double-click, not a decision.
    now.mockReturnValue(1_100)
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm delete rules.pdf' }))
    expect(actions.remove).not.toHaveBeenCalled()
    now.mockReturnValue(2_000)
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm delete rules.pdf' }))
    expect(actions.remove).toHaveBeenCalledWith(file)
    now.mockRestore()
  })

  it('never deletes on a double-click, and names the note it would delete', async () => {
    const note = entry({ id: 'n2', section: 'details', text: 'Keep the 6S pack under 45 °C' })
    state.current = ready([note])
    render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Project details'))
    const button = within(screen.getByTestId('solus-entry-n2')).getByRole('button', {
      name: 'Delete Keep the 6S pack under 45 °C'
    })
    await userEvent.dblClick(button)
    expect(actions.remove).not.toHaveBeenCalled()
    expect(button).toHaveAccessibleName('Confirm delete Keep the 6S pack under 45 °C')
  })

  it('renders hostile entry text as text, never as markup', async () => {
    // §7 red-team fixture: `text` on a SOL-filed row is model output; `name`
    // and `media_type` are upload- and connector-influenced.
    const hostile = '<img src=x onerror="alert(1)">'
    state.current = ready([
      entry({ id: 'x1', section: 'errors', author: 'sol', text: hostile }),
      entry({
        id: 'x2',
        section: 'errors',
        kind: 'artifact',
        text: null,
        name: '<script>alert(1)</script>.pdf',
        media_type: '<b>x</b>',
        size_bytes: 10
      })
    ])
    const { container } = render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Error logging'))
    expect(screen.getByText(hostile)).toBeInTheDocument()
    expect(screen.getByText('<script>alert(1)</script>.pdf')).toBeInTheDocument()
    expect(screen.getByText(/<b>x<\/b>/)).toBeInTheDocument()
    expect(container.querySelector('img, script, b')).toBeNull()
  })

  it('imports a picked file into the open section', async () => {
    render(<SolusCard projectId="p1" projectName="Rover" />)
    await userEvent.click(row('Documentation'))
    await userEvent.click(screen.getByRole('button', { name: 'Import file' }))
    const picked = new File(['%PDF'], 'datasheet.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Import a file into .solus'), {
      target: { files: [picked] }
    })
    expect(actions.importFile).toHaveBeenCalledWith('docs', picked)
  })
})
