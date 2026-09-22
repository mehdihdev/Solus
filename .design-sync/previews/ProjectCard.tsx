import { ProjectCard } from '@solus/desktop'

const noop = (): void => {}
const noopTrue = async (): Promise<boolean> => true

const ago = (minutes: number): string => new Date(Date.now() - minutes * 60_000).toISOString()

const ACTIONS = {
  switchTeam: noop,
  createProject: async () => null,
  createTeam: async () => ({ ok: true }),
  joinTeam: async () => ({ ok: true }),
  renameProject: noopTrue,
  editProject: noopTrue,
  archiveProject: noopTrue,
  unarchiveProject: noopTrue,
  deleteProject: noopTrue,
  refresh: async (): Promise<void> => {}
}

const ARI = {
  id: 'p-ari-02',
  team_id: 't-solus-robotics',
  name: 'Ari-02',
  description: 'Quadruped test platform — KiCad main board, Onshape chassis, ROS 2 stack.',
  archived_at: null,
  created_at: ago(60 * 24 * 40),
  updated_at: ago(12)
}

const ACTIVITY = [
  {
    id: 'a-1',
    type: 'source.connected',
    domain: 'electrical',
    actor_id: 'u-1',
    project_id: ARI.id,
    payload: { type: 'kicad', name: 'main-board.kicad_pcb' },
    created_at: ago(9)
  },
  {
    id: 'a-2',
    type: 'source.sync_started',
    domain: 'mechanical',
    actor_id: 'u-2',
    project_id: ARI.id,
    payload: {},
    created_at: ago(47)
  }
]

const box = { width: 340 } as const

export function OpenProject() {
  return (
    <div style={box}>
      <ProjectCard
        project={ARI}
        activity={ACTIVITY}
        currentProjectId={null}
        canManage
        canDelete
        actions={ACTIONS}
        onOpen={noop}
        onSwitch={noop}
        onActionFailed={noop}
      />
    </div>
  )
}

export function SwitchToProject() {
  return (
    <div style={box}>
      <ProjectCard
        project={{
          ...ARI,
          id: 'p-strider',
          name: 'Strider',
          description: 'Biped balance research rig — shares the Ari-02 driver board.'
        }}
        activity={ACTIVITY}
        currentProjectId={ARI.id}
        canManage
        canDelete={false}
        actions={ACTIONS}
        onOpen={noop}
        onSwitch={noop}
        onActionFailed={noop}
      />
    </div>
  )
}

export function NoActivityViewer() {
  return (
    <div style={box}>
      <ProjectCard
        project={{
          ...ARI,
          id: 'p-fsae-ev',
          name: 'FSAE EV accumulator',
          description: null
        }}
        activity={[]}
        currentProjectId={null}
        canManage={false}
        canDelete={false}
        actions={ACTIONS}
        onOpen={noop}
        onSwitch={noop}
        onActionFailed={noop}
      />
    </div>
  )
}
