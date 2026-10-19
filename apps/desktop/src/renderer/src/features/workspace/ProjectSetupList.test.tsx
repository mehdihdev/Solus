// Home's PROJECT SETUP card (SOLUSDEV-317, concept 1): this computer, the
// sources and .solus as one list, each part keeping its own component.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectSetupList } from './ProjectSetupList'

vi.mock('../project/ProjectFolderCard', () => ({
  ProjectFolderCard: (p: { projectId: string; compact?: boolean; bare?: boolean }) => (
    <div data-testid="folder" data-compact={String(!!p.compact)} data-bare={String(!!p.bare)} />
  )
}))
vi.mock('./ProjectSourcesSummary', () => ({
  ProjectSourcesSummary: ({ onAdd }: { onAdd: () => void }) => (
    <button type="button" onClick={onAdd}>
      Add additional sources
    </button>
  )
}))
vi.mock('./SolusSummaryRow', () => ({
  SolusSummaryRow: ({ onAddInstructions }: { onAddInstructions: () => void }) => (
    <button type="button" onClick={onAddInstructions}>
      Add instructions
    </button>
  )
}))

describe('ProjectSetupList', () => {
  it('lists this computer, sources and .solus under one PROJECT SETUP heading', async () => {
    const onAddSources = vi.fn()
    const onAddInstructions = vi.fn()
    render(
      <ProjectSetupList
        project={{ id: 'p1', name: 'Rover', teamId: 't1' }}
        onAddSources={onAddSources}
        onAddInstructions={onAddInstructions}
      />
    )
    expect(screen.getByText('PROJECT SETUP')).toBeInTheDocument()
    expect(screen.getByText('ON THIS COMPUTER')).toBeInTheDocument()
    expect(screen.getByText('.SOLUS — WHAT SOL KNOWS')).toBeInTheDocument()
    expect(screen.getByTestId('folder')).toHaveAttribute('data-bare', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Add additional sources' }))
    expect(onAddSources).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Add instructions' }))
    expect(onAddInstructions).toHaveBeenCalled()
  })
})
