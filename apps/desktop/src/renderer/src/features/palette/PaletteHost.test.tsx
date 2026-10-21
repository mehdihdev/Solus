import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { PaletteHost, type PaletteHostProps } from './PaletteHost'
import { usePaletteStore } from './paletteStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as events from './paletteEvents'
import * as actions from './paletteActions'

const data = vi.hoisted(() => ({
  switcher: { status: 'ready', groups: [] as unknown[] },
  graph: { status: 'ready', entities: [] as unknown[] | null }
}))
vi.mock('../workspace/useProjectSwitcher', () => ({ useProjectSwitcher: () => data.switcher }))
vi.mock('../graph/useWorkspaceGraph', () => ({ useWorkspaceGraph: () => data.graph }))
vi.mock('./paletteEvents', () => ({ reportPaletteOpened: vi.fn() }))
vi.mock('./paletteActions', () => ({ runPaletteTarget: vi.fn() }))

const team = {
  team_id: 't1',
  name: 'Rover Lab',
  role: 'owner',
  is_personal: false,
  plan_status: '',
  trial_ends_at: ''
}
const project = {
  id: 'p1',
  team_id: 't1',
  name: 'Mars Rover',
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: ''
}

function renderHost(): PaletteHostProps {
  const props = {
    go: vi.fn(),
    openExtensionPage: vi.fn(),
    extensions: [{ slug: 'bom', label: 'BOM' }]
  }
  render(<PaletteHost {...props} />)
  return props
}

beforeEach(() => {
  vi.clearAllMocks()
  usePaletteStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Mars Rover', teamId: 't1' } })
  data.switcher = { status: 'ready', groups: [{ team, projects: [project] }] }
  data.graph = {
    status: 'ready',
    entities: [{ id: 'e1', name: 'IMU', type: 'sensor', domain: 'ee', source_key: null }]
  }
})

describe('PaletteHost', () => {
  it('renders nothing until opened, then opens from the store', () => {
    renderHost()
    expect(screen.queryByRole('dialog')).toBeNull()
    act(() => usePaletteStore.getState().setOpen(true))
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeInTheDocument()
  })

  it('searches pages, extension pages, projects, teams and the open project nodes', () => {
    renderHost()
    act(() => usePaletteStore.getState().setOpen(true))
    const input = screen.getByRole('combobox')
    for (const [query, label] of [
      ['bench', 'Live Bench'],
      ['bom', 'BOM'],
      ['mars', 'Mars Rover'],
      ['lab', 'Rover Lab'],
      ['imu', 'IMU']
    ]) {
      fireEvent.change(input, { target: { value: query } })
      expect(screen.getAllByText(label)[0]).toBeInTheDocument()
    }
  })

  it('opens a pick: closes, remembers it, reports it and runs its target', () => {
    const props = renderHost()
    act(() => usePaletteStore.getState().setOpen(true))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'imu' } })
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' })
    expect(usePaletteStore.getState()).toMatchObject({ open: false, recentKeys: ['node:p1:e1'] })
    expect(events.reportPaletteOpened).toHaveBeenCalledWith('node', 0, 'imu')
    expect(actions.runPaletteTarget).toHaveBeenCalledWith(
      { type: 'node', projectId: 'p1', entityId: 'e1' },
      { go: props.go, openExtensionPage: props.openExtensionPage }
    )
  })

  it('offers no nodes without an open project', () => {
    useWorkspaceStore.setState({ project: null })
    renderHost()
    act(() => usePaletteStore.getState().setOpen(true))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'imu' } })
    expect(screen.queryByText('IMU')).toBeNull()
  })

  it('shows loading while projects or the graph are still arriving', () => {
    data.graph = { status: 'loading', entities: null }
    renderHost()
    act(() => usePaletteStore.getState().setOpen(true))
    expect(screen.getByRole('status')).toHaveTextContent('Loading…')
  })

  it('toggles with the keyboard shortcut and closes on Escape', () => {
    renderHost()
    const mac = /mac/i.test(navigator.platform)
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: mac, ctrlKey: !mac }))
    })
    expect(usePaletteStore.getState().open).toBe(true)
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' })
    expect(usePaletteStore.getState().open).toBe(false)
  })
})
