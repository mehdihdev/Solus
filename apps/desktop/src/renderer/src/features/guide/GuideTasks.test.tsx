import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { GuideTasks } from './GuideTasks'
import { listGuides, getGuide } from './guideApi'
import { useWorkspaceStore } from '../../store/workspaceStore'
vi.mock('./guideApi', () => ({ listGuides: vi.fn(), getGuide: vi.fn(), sendFeedback: vi.fn() }))
beforeEach(() => {
  vi.mocked(listGuides).mockResolvedValue([
    { id: 'hole', tool: 'onshape', title: 'Add a 6 mm hole', summary: '', step_count: 1 }
  ])
  vi.mocked(getGuide).mockResolvedValue({
    id: 'hole',
    tool: 'onshape',
    title: 'Add a 6 mm hole',
    summary: '',
    steps: []
  })
})
it('loads an authored browser walkthrough without invoking any tool', async () => {
  render(<GuideTasks />)
  fireEvent.change(screen.getByLabelText('Guide tool'), { target: { value: 'onshape' } })
  await screen.findByRole('option', { name: 'Add a 6 mm hole' })
  fireEvent.change(screen.getByLabelText('Guide task'), { target: { value: 'hole' } })
  expect(await screen.findByRole('heading', { name: 'Add a 6 mm hole' })).toBeInTheDocument()
  expect(screen.getByText(/compatibility convention/)).toBeInTheDocument()
})
it('expires pending tasks across a batched project A B A change', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof listGuides>>) => void
  vi.mocked(listGuides).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  useWorkspaceStore.setState({ project: { id: 'a', name: 'A' } })
  render(<GuideTasks />)
  fireEvent.change(screen.getByLabelText('Guide tool'), { target: { value: 'onshape' } })
  act(() => {
    useWorkspaceStore.setState({ project: { id: 'b', name: 'B' } })
    useWorkspaceStore.setState({ project: { id: 'a', name: 'A' } })
  })
  await act(async () => {
    resolve([{ id: 'stale', tool: 'onshape', title: 'Stale task', summary: '', step_count: 1 }])
  })
  expect(screen.queryByText('Stale task')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Guide tool')).toHaveValue('')
})
it('keeps native guidance honest when no trusted window target exists', () => {
  render(<GuideTasks />)
  fireEvent.change(screen.getByLabelText('Guide tool'), { target: { value: 'kicad' } })
  expect(screen.getByText(/window location is unavailable/)).toBeInTheDocument()
})

it('presents scriptable instructions as copy-only with unavailable KB controls', async () => {
  const clipboard = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: clipboard }
  })
  vi.mocked(listGuides).mockResolvedValue([
    { id: 'fixture', tool: 'code', title: 'Fixture instructions', summary: '', step_count: 1 }
  ])
  vi.mocked(getGuide).mockResolvedValue({
    id: 'fixture',
    tool: 'code',
    title: 'Fixture instructions',
    summary: '',
    steps: [
      {
        step_number: 1,
        control_id: 'fixture.unknown',
        entry_id: null,
        note_guide: 'python --version',
        note_expert: 'python --version',
        available: false,
        tentative: true,
        stale: false,
        label: null,
        description: null,
        shortcut: null,
        menu_path: null,
        surface: 'toolbar',
        confidence: null,
        locator: null
      }
    ]
  })
  render(<GuideTasks />)
  fireEvent.change(screen.getByLabelText('Guide tool'), { target: { value: 'code' } })
  fireEvent.change(screen.getByLabelText('Installed tool version'), { target: { value: '1.0' } })
  await screen.findByRole('option', { name: 'Fixture instructions' })
  fireEvent.change(screen.getByLabelText('Guide task'), { target: { value: 'fixture' } })
  fireEvent.click(await screen.findByRole('button', { name: 'Copy instruction' }))
  expect(clipboard).toHaveBeenCalledWith('python --version')
  expect(screen.getByText(/Not sure where that is in this version/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /run|execute/i })).not.toBeInTheDocument()
  Reflect.deleteProperty(navigator, 'clipboard')
})
