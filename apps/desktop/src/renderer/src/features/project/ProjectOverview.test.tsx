// Project hub / overview screen (SOLUSDEV-164): the landing when a project is
// opened. Orients the user with the project's stats + sources and links into
// each domain, instead of dumping them straight into the Context Model.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectOverview } from './ProjectOverview'
import * as hook from './useProjectOverview'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Source } from '../../lib/api/resources'
import * as resources from '../../lib/api/resources'

vi.mock('./useProjectOverview', () => ({ useProjectOverview: vi.fn() }))
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, updateProject: vi.fn() }
})

const SOURCE = (id: string): Source =>
  ({
    id,
    project_id: 'p1',
    type: 'github',
    name: `octo/${id}`,
    status: 'connected',
    config: {},
    account_login: null,
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: ''
  }) as Source

function mockOverview(value: Partial<hook.ProjectOverview>): void {
  vi.mocked(hook.useProjectOverview).mockReturnValue({
    status: 'ready',
    id: 'p1',
    name: 'Rover MK2',
    description: 'a quadruped',
    entityCount: 12,
    relationCount: 30,
    sources: [SOURCE('arm')],
    refresh: vi.fn(),
    ...value
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('ProjectOverview', () => {
  it('prompts to pick a project when none is open', () => {
    mockOverview({ status: 'offline', name: '' })
    render(<ProjectOverview onNavigate={vi.fn()} />)
    expect(screen.getByText(/select a project/i)).toBeInTheDocument()
  })

  it('shows the project name, description, and real counts', () => {
    mockOverview({})
    render(<ProjectOverview onNavigate={vi.fn()} />)
    expect(screen.getByText('Rover MK2')).toBeInTheDocument()
    expect(screen.getByText('a quadruped')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('30')).toBeInTheDocument()
  })

  it('navigates into the Workspace domain', async () => {
    mockOverview({})
    const onNavigate = vi.fn()
    render(<ProjectOverview onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /workspace/i }))
    expect(onNavigate).toHaveBeenCalledWith('workspace')
  })

  it('navigates to Sources to manage integrations', async () => {
    mockOverview({})
    const onNavigate = vi.fn()
    render(<ProjectOverview onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /manage sources/i }))
    expect(onNavigate).toHaveBeenCalledWith('sources')
  })

  it('shows a connect CTA when the project has no sources', async () => {
    mockOverview({ sources: [] })
    const onNavigate = vi.fn()
    render(<ProjectOverview onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /connect a tool/i }))
    expect(onNavigate).toHaveBeenCalledWith('sources')
  })

  it('edits the name and description, persisting and updating the topbar label', async () => {
    mockOverview({})
    const refresh = vi.fn().mockResolvedValue(undefined)
    vi.mocked(hook.useProjectOverview).mockReturnValue({
      status: 'ready',
      id: 'p1',
      name: 'Rover MK2',
      description: 'a quadruped',
      entityCount: 12,
      relationCount: 30,
      sources: [],
      refresh
    })
    vi.mocked(resources.updateProject).mockResolvedValue({} as never)
    // The Overview only renders for the OPEN project; the rename keeps it in step.
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2' } })
    render(<ProjectOverview onNavigate={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const name = screen.getByLabelText('Project name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Rover MK3')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(resources.updateProject).toHaveBeenCalledWith('p1', {
        name: 'Rover MK3',
        description: 'a quadruped'
      })
    )
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p1', name: 'Rover MK3' })
    expect(refresh).toHaveBeenCalled()
  })

  it('renaming keeps the project’s team — a rename is not a switch (SOLUSDEV-242)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    vi.mocked(hook.useProjectOverview).mockReturnValue({
      status: 'ready',
      id: 'p1',
      name: 'Rover MK2',
      description: '',
      entityCount: 0,
      relationCount: 0,
      sources: [],
      refresh: vi.fn().mockResolvedValue(undefined)
    })
    vi.mocked(resources.updateProject).mockResolvedValue({} as never)
    render(<ProjectOverview onNavigate={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const name = screen.getByLabelText('Project name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Rover MK3')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(useWorkspaceStore.getState().project).toEqual({
        id: 'p1',
        name: 'Rover MK3',
        teamId: 't1'
      })
    )
  })

  it('offers a local folder section for the open project', () => {
    mockOverview({})
    render(<ProjectOverview onNavigate={vi.fn()} />)
    expect(screen.getByText('LOCAL FOLDER')).toBeInTheDocument()
  })
})
