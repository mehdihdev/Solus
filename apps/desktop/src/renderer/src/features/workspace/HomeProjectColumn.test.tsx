// SOLUSDEV-328 — on a wide Home the current project gets its own column beside the overview: its
// header (Live Bench, Open workspace), sources and .solus side by side, then the project's own
// activity filling the height. No current project in this team: a plain prompt, nothing invented.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HomeProjectColumn, type HomeProjectColumnProps } from './HomeProjectColumn'

vi.mock('./ProjectSourcesSummary', () => ({
  ProjectSourcesSummary: () => <div>sources summary</div>
}))
vi.mock('./SolusSummaryRow', () => ({
  SolusSummaryRow: ({ onAddInstructions }: { onAddInstructions: () => void }) => (
    <button type="button" onClick={onAddInstructions}>
      Add instructions
    </button>
  )
}))
vi.mock('./ProjectActivityFeed', () => ({
  ProjectActivityFeed: ({ project }: { project: { id: string } }) => (
    <div>activity for {project.id}</div>
  )
}))

function props(overrides: Partial<HomeProjectColumnProps> = {}): HomeProjectColumnProps {
  return {
    project: { id: 'p1', name: 'Rover MK2', teamId: 't-arm' },
    description: 'Six-wheel rover',
    repos: [],
    onOpen: vi.fn(),
    onBench: vi.fn(),
    onManageSources: vi.fn(),
    onAddInstructions: vi.fn(),
    ...overrides
  }
}

describe('HomeProjectColumn', () => {
  it('heads the column with the project and its two ways in', async () => {
    const p = props()
    render(<HomeProjectColumn {...p} />)
    expect(screen.getByRole('region', { name: 'Rover MK2' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Rover MK2' })).toBeInTheDocument()
    expect(screen.getByText('Six-wheel rover')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Live Bench' }))
    await userEvent.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(p.onBench).toHaveBeenCalled()
    expect(p.onOpen).toHaveBeenCalled()
  })

  it('shows sources, .solus and the project activity at once, without tabs', async () => {
    const p = props()
    render(<HomeProjectColumn {...p} />)
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(screen.getByText('sources summary')).toBeInTheDocument()
    expect(screen.getByText('activity for p1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add instructions' }))
    expect(p.onAddInstructions).toHaveBeenCalled()
  })

  it('asks for a pick when no project of this team is current', () => {
    render(<HomeProjectColumn {...props({ project: null })} />)
    expect(screen.getByText('Pick a project to see it here.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open workspace' })).toBeNull()
  })

  it('names a project whose team is unknown instead of loading its feed', () => {
    render(<HomeProjectColumn {...props({ project: { id: 'p1', name: 'Rover MK2' } })} />)
    expect(screen.queryByText('activity for p1')).toBeNull()
    expect(screen.getByText(/reopen it from the list/)).toBeInTheDocument()
  })
})
