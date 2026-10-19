// The project ⋯ menu (SOLUSDEV-242, moved for SOLUSDEV-317): actions, the
// owner-only Delete (ADR-025), and the toast on a failed archive.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectMenu } from './ProjectMenu'
import type { Project } from '../../lib/api/resources'
import type { HomeActions } from './useHomeData'

const PROJECT: Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: ''
}

function actions(archived: boolean): HomeActions {
  return {
    archiveProject: vi.fn().mockResolvedValue(archived),
    deleteProject: vi.fn().mockResolvedValue(true),
    editProject: vi.fn()
  } as unknown as HomeActions
}

async function openMenu(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
}

describe('ProjectMenu', () => {
  it('archives, and reports a failed archive by name', async () => {
    const a = actions(false)
    const onActionFailed = vi.fn()
    render(<ProjectMenu project={PROJECT} canDelete actions={a} onActionFailed={onActionFailed} />)
    await openMenu()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Archive' }))
    expect(a.archiveProject).toHaveBeenCalledWith('p1')
    await vi.waitFor(() =>
      expect(onActionFailed).toHaveBeenCalledWith('Couldn\'t archive "Rover MK2".')
    )
  })

  it('deletes only after the confirm dialog', async () => {
    const a = actions(true)
    render(<ProjectMenu project={PROJECT} canDelete actions={a} onActionFailed={vi.fn()} />)
    await openMenu()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(a.deleteProject).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /^delete project$/i }))
    expect(a.deleteProject).toHaveBeenCalledWith('p1')
  })

  it('hides Delete without the owner role', async () => {
    render(
      <ProjectMenu
        project={PROJECT}
        canDelete={false}
        actions={actions(true)}
        onActionFailed={vi.fn()}
      />
    )
    await openMenu()
    expect(screen.getByRole('menuitem', { name: 'Edit details' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Delete' })).toBeNull()
  })
})
