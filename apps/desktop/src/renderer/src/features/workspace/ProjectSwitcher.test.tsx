// Topbar project switcher (SOLUSDEV-164): shows the open project's name and, on
// click, a dropdown to jump to another project or back to all projects (Home).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectSwitcher } from './ProjectSwitcher'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getMe: vi.fn(), listProjects: vi.fn() }
})

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
  vi.mocked(resources.getMe).mockResolvedValue({
    id: 'u1',
    email: 'a@b.dev',
    name: null,
    avatar_url: null,
    created_at: '',
    teams: [{ team_id: 't1', name: 'Acme', role: 'member', is_personal: false }]
  } as resources.Me)
  vi.mocked(resources.listProjects).mockResolvedValue([
    {
      id: 'p2',
      team_id: 't1',
      name: 'Rover MK3',
      description: null,
      archived_at: null,
      created_at: '',
      updated_at: ''
    } as resources.Project
  ])
})

describe('ProjectSwitcher', () => {
  it('shows the honest no-project label when none is open', () => {
    render(<ProjectSwitcher onSwitch={vi.fn()} onHome={vi.fn()} />)
    expect(screen.getByText('No project')).toBeInTheDocument()
  })

  it('shows the open project name', () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    render(<ProjectSwitcher onSwitch={vi.fn()} onHome={vi.fn()} />)
    expect(screen.getByText('Strider')).toBeInTheDocument()
  })

  it('opens a dropdown and switches project', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    const onSwitch = vi.fn()
    render(<ProjectSwitcher onSwitch={onSwitch} onHome={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    const target = await screen.findByText('Rover MK3')
    await userEvent.click(target)
    expect(onSwitch).toHaveBeenCalledWith({ id: 'p2', name: 'Rover MK3' })
  })

  it('offers a way back to all projects (Home)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    const onHome = vi.fn()
    render(<ProjectSwitcher onSwitch={vi.fn()} onHome={onHome} />)
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(screen.getByText(/all projects/i))
    expect(onHome).toHaveBeenCalled()
  })
})
