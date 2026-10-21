import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { runPaletteTarget } from './paletteActions'
import { usePaletteStore } from './paletteStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as projectSwitch from '../workspace/projectSwitch'
import * as teamSwitch from '../workspace/teamSwitch'

vi.mock('../workspace/projectSwitch', () => ({ switchWorkspaceProject: vi.fn() }))
vi.mock('../workspace/teamSwitch', () => ({ switchWorkspaceTeam: vi.fn() }))

const actions = (): { go: Mock; openExtensionPage: Mock } => ({
  go: vi.fn(),
  openExtensionPage: vi.fn()
})

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover', teamId: 't1' } })
  usePaletteStore.getState().reset()
})

describe('runPaletteTarget', () => {
  it('navigates to a screen', () => {
    const a = actions()
    runPaletteTarget({ type: 'screen', screen: 'bench' }, a)
    expect(a.go).toHaveBeenCalledWith('bench')
  })

  it("opens an extension's page view", () => {
    const a = actions()
    runPaletteTarget({ type: 'extension', slug: 'bom' }, a)
    expect(a.openExtensionPage).toHaveBeenCalledWith('bom')
  })

  it('opens a project through the switch choke point and lands on its Workspace', () => {
    const a = actions()
    const project = { id: 'p2', name: 'Car', teamId: 't2' }
    runPaletteTarget({ type: 'project', project }, a)
    expect(projectSwitch.switchWorkspaceProject).toHaveBeenCalledWith(project, 'palette')
    expect(a.go).toHaveBeenCalledWith('workspace')
  })

  it('switches team through the team choke point and lands on Home', () => {
    const a = actions()
    runPaletteTarget({ type: 'team', teamId: 't2' }, a)
    expect(teamSwitch.switchWorkspaceTeam).toHaveBeenCalledWith('t2', 'palette')
    expect(a.go).toHaveBeenCalledWith('home')
  })

  it('jumps to a node of the open project on the Workspace', () => {
    const a = actions()
    runPaletteTarget({ type: 'node', projectId: 'p1', entityId: 'e1' }, a)
    expect(usePaletteStore.getState().jump).toMatchObject({ projectId: 'p1', entityId: 'e1' })
    expect(a.go).toHaveBeenCalledWith('workspace')
  })

  it('refuses a node from a project that is no longer open', () => {
    const a = actions()
    runPaletteTarget({ type: 'node', projectId: 'p9', entityId: 'e1' }, a)
    expect(usePaletteStore.getState().jump).toBeNull()
    expect(a.go).not.toHaveBeenCalled()
  })
})
