// The robot sidebar (SOLUSDEV-250 P4): everything the robot card and the delete modal
// used to offer, plus what the graph snapshot and the per-robot reads can prove —
// categories from `contains` edges, connection from active real bench sessions, pending
// suggestions, provenance tags only when the config carries them. Nothing invented.
import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../../../lib/api/physicalRobots'
import * as hardwareApi from '../../../lib/api/hardware'
import * as resources from '../../../lib/api/resources'
import type { Entity, Relation } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { usePhysicalRobots } from '../robots/usePhysicalRobots'

vi.mock('../../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn(),
  listRobotOrphans: vi.fn()
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listHardwareSuggestions: vi.fn(),
  acceptHardwareSuggestion: vi.fn(),
  rejectHardwareSuggestion: vi.fn(),
  getHardwareConfig: vi.fn(),
  listUnassignedParts: vi.fn(),
  attachParts: vi.fn()
}))
vi.mock('../../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/resources')>()),
  listBenchSessions: vi.fn()
}))

const robot: Entity = {
  id: 'robot-1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  source_id: null,
  origin: 'manual',
  version: 1
}
const sensors: Entity = {
  ...robot,
  id: 'cat-sensors',
  name: 'Sensors',
  type: 'robot_category',
  properties: { robot_id: robot.id, category: 'sensors' }
}
const actuators: Entity = {
  ...sensors,
  id: 'cat-actuators',
  name: 'Actuators / motors',
  properties: { robot_id: robot.id, category: 'actuators' }
}
const imu: Entity = {
  ...robot,
  id: 'imu',
  name: 'Wrist IMU',
  type: 'sensor',
  domain: 'electrical',
  source_key: 'usb:abc/1'
}
const motor: Entity = {
  ...robot,
  id: 'motor',
  name: 'Drive motor',
  type: 'motor',
  domain: 'mechanical',
  source_key: null
}
const orphan: Entity = {
  ...motor,
  id: 'orphan-1',
  name: 'Spare servo',
  properties: { category: 'actuators' }
}
const contains = (from: Entity, to: Entity): Relation => ({
  id: `${from.id}>${to.id}`,
  type: 'contains',
  from_entity_id: from.id,
  to_entity_id: to.id
})
// Reads are cached per snapshot array, so every test gets a fresh one (see beforeEach).
let ENTITIES: Entity[] = []
const RELATIONS = [
  contains(robot, sensors),
  contains(robot, actuators),
  contains(sensors, imu),
  contains(actuators, motor)
]
const session = (device_ref: string | null): resources.BenchSession => ({
  id: 's1',
  mode: 'real',
  provider: 'robot',
  status: 'active',
  link: 'live' as resources.BenchSession['link'],
  label: 'Rover',
  created_at: '',
  ended_at: null,
  device: { serial_number: null, device_path: null, baud: null, device_ref },
  device_ids: [],
  counts: { ingested: 1, unresolved: 0 },
  last_summary: null
})
const suggestion = (
  over: Partial<hardwareApi.HardwareSuggestion>
): hardwareApi.HardwareSuggestion => ({
  id: 's-1',
  subject_ref: 'usb:abc',
  subject_kind: 'device',
  candidate_robot_id: robot.id,
  confidence: 0.8,
  tier: 'high',
  evidence: [],
  reason: 'Six servos answered on the bus.',
  status: 'pending',
  created_at: '',
  decided_at: null,
  ...over
})

const changed = vi.fn()
const reveal = vi.fn()
function Harness({
  entities = ENTITIES,
  relations = RELATIONS,
  selected = robot.id
}: {
  entities?: Entity[]
  relations?: Relation[]
  selected?: string
}): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const robots = usePhysicalRobots(projectId, changed, reveal, entities, relations)
  const entity = entities.find((candidate) => candidate.id === selected)
  return <>{entity && robots.renderSidebar(entity)}</>
}
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  vi.resetAllMocks()
  ENTITIES = [robot, sensors, actuators, imu, motor]
  useAuthStore.setState({ status: 'authenticated', user: { email: 'robot@example.invalid' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.mocked(hardwareApi.listUnassignedParts).mockResolvedValue({
    data: [],
    meta: { has_next: false }
  })
  vi.mocked(resources.listBenchSessions).mockResolvedValue([])
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([])
  vi.mocked(hardwareApi.getHardwareConfig).mockRejectedValue(new ApiError(404, 'not_found', 'No'))
  vi.mocked(api.renamePhysicalRobot).mockResolvedValue({ ...robot, name: 'Scout', version: 2 })
  vi.mocked(api.deletePhysicalRobot).mockResolvedValue({
    deleted_entity_id: robot.id,
    retained_part_ids: [motor.id]
  })
})

it('lists the seven categories in order with counts from the snapshot, empty ones honestly', async () => {
  render(<Harness />)
  expect(screen.getByRole('heading', { name: 'Rover' })).toBeInTheDocument()
  const headings = within(screen.getByRole('region', { name: 'Parts' }))
    .getAllByRole('heading', { level: 3 })
    .map((heading) => heading.textContent)
  expect(headings).toEqual([
    'Sensors · 1',
    'Actuators / motors · 1',
    'Controllers · 0',
    'End effectors · 0',
    'Power · 0',
    'Structure · 0',
    'Wiring · 0'
  ])
  expect(screen.getByRole('button', { name: 'Reveal Wrist IMU' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reveal Drive motor' })).toBeInTheDocument()
  expect(screen.getAllByText(/none yet/)).toHaveLength(5)
  await userEvent.click(screen.getByRole('button', { name: 'Reveal Wrist IMU' }))
  expect(reveal).toHaveBeenCalledWith(imu.id)
})

it('reports streaming when an active real session matches a part device ref', async () => {
  vi.mocked(resources.listBenchSessions).mockResolvedValue([session('usb:abc')])
  render(<Harness />)
  expect(await screen.findByText('Connected · session open')).toBeInTheDocument()
  expect(resources.listBenchSessions).toHaveBeenCalledExactlyOnceWith('p1', {
    status: 'active',
    mode: 'real'
  })
})

it('reports not connected when no session matches, tolerating null source keys', async () => {
  vi.mocked(resources.listBenchSessions).mockResolvedValue([session('usb:other'), session(null)])
  render(<Harness />)
  expect(await screen.findByText('Not connected')).toBeInTheDocument()
})

it('says unknown when the sessions read fails, and offline without asking', async () => {
  vi.mocked(resources.listBenchSessions).mockRejectedValue(new Error('down'))
  const view = render(<Harness />)
  expect(await screen.findByText('Unknown (offline)')).toBeInTheDocument()
  view.unmount()
  vi.mocked(resources.listBenchSessions).mockClear()
  vi.mocked(hardwareApi.listHardwareSuggestions).mockClear()
  useAuthStore.setState({ status: 'unauthenticated', user: null })
  render(<Harness />)
  expect(screen.getByText('Unknown (offline)')).toBeInTheDocument()
  expect(resources.listBenchSessions).not.toHaveBeenCalled()
  expect(hardwareApi.listHardwareSuggestions).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete robot…' })).not.toBeInTheDocument()
})

it('shows only this robot’s pending suggestions with their verbatim reason; Accept and Reject decide', async () => {
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([
    suggestion({}),
    suggestion({ id: 's-2', subject_ref: 'usb:zzz', candidate_robot_id: 'robot-2' })
  ])
  vi.mocked(hardwareApi.acceptHardwareSuggestion).mockResolvedValue(
    suggestion({ status: 'accepted' })
  )
  vi.mocked(hardwareApi.rejectHardwareSuggestion).mockResolvedValue(
    suggestion({ status: 'rejected' })
  )
  render(<Harness />)
  const row = await screen.findByRole('listitem', { name: 'usb:abc' })
  expect(screen.queryByText('usb:zzz')).not.toBeInTheDocument()
  expect(within(row).getByText('Six servos answered on the bus.')).toBeInTheDocument()
  await userEvent.click(within(row).getByRole('button', { name: 'Accept' }))
  expect(hardwareApi.acceptHardwareSuggestion).toHaveBeenCalledExactlyOnceWith('p1', 's-1')
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
  await userEvent.click(within(row).getByRole('button', { name: 'Reject' }))
  expect(hardwareApi.rejectHardwareSuggestion).toHaveBeenCalledExactlyOnceWith('p1', 's-1')
})

it('keeps a failed decision visible', async () => {
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([suggestion({})])
  vi.mocked(hardwareApi.acceptHardwareSuggestion).mockRejectedValue(new Error('Gone stale'))
  render(<Harness />)
  await userEvent.click(await screen.findByRole('button', { name: 'Accept' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Gone stale')
  expect(changed).not.toHaveBeenCalled()
})

it('tags a part with its config provenance only when the wire carries one', async () => {
  vi.mocked(hardwareApi.getHardwareConfig).mockResolvedValue({
    entry_id: 'entry',
    robot_entity_id: robot.id,
    config: {
      schema_version: 1,
      robot_entity_id: robot.id,
      provenance: {
        'parts.imu.lifecycle': { by: 'detected', source: 'usb:abc' },
        'parts.imu.calibration.mode': { by: 'repo' }
      }
    }
  })
  render(<Harness />)
  const imuRow = await screen.findByRole('listitem', { name: 'Wrist IMU' })
  await waitFor(() => expect(within(imuRow).getByText('detected/repo')).toBeInTheDocument())
  expect(hardwareApi.getHardwareConfig).toHaveBeenCalledExactlyOnceWith('p1', robot.id)
  expect(
    within(screen.getByRole('listitem', { name: 'Drive motor' })).queryByText(/detected|repo|user/)
  ).toBeNull()
})

it('offers Attach to <robot> on each unassigned part and refreshes after attaching', async () => {
  vi.mocked(hardwareApi.listUnassignedParts).mockResolvedValue({
    data: [orphan],
    meta: { has_next: false }
  })
  vi.mocked(hardwareApi.attachParts).mockResolvedValue({
    attached: [orphan.id],
    skipped: [],
    config_entry_id: 'entry'
  })
  render(<Harness />)
  expect(await screen.findByRole('button', { name: 'Reveal Spare servo' })).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Category' })).toHaveValue('actuators')
  await userEvent.click(screen.getByRole('button', { name: 'Attach to Rover' }))
  expect(hardwareApi.attachParts).toHaveBeenCalledExactlyOnceWith('p1', robot.id, {
    entity_ids: [orphan.id],
    category: 'actuators'
  })
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
})

it('keeps an attach failure visible', async () => {
  vi.mocked(hardwareApi.listUnassignedParts).mockResolvedValue({
    data: [orphan],
    meta: { has_next: false }
  })
  vi.mocked(hardwareApi.attachParts).mockRejectedValue(
    new ApiError(409, 'conflict', 'Spare servo already belongs to another robot')
  )
  render(<Harness />)
  await userEvent.click(await screen.findByRole('button', { name: 'Attach to Rover' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/already belongs/)
  expect(changed).not.toHaveBeenCalled()
})

it('renames from the heading, trims the name, and cancels cleanly', async () => {
  render(<Harness />)
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  const input = screen.getByRole('textbox', { name: 'Robot name' })
  expect(input).toHaveAttribute('maxlength', '512')
  await userEvent.clear(input)
  await userEvent.type(input, '   ')
  expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled()
  await userEvent.clear(input)
  await userEvent.type(input, '  Scout  ')
  await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
  expect(api.renamePhysicalRobot).toHaveBeenCalledWith('p1', robot, 'Scout', expect.anything())
  expect(changed).toHaveBeenCalledOnce()
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel rename' }))
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('textbox', { name: 'Robot name' })).not.toBeInTheDocument()
})

it('keeps a failed rename draft, refreshes conflicts, and retries only with a fresh version', async () => {
  vi.mocked(api.renamePhysicalRobot)
    .mockRejectedValueOnce(new ApiError(409, 'conflict', 'Changed'))
    .mockResolvedValue({ ...robot, name: 'Scout', version: 3 })
  const view = render(<Harness />)
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  const input = screen.getByRole('textbox', { name: 'Robot name' })
  await userEvent.clear(input)
  await userEvent.type(input, 'Scout')
  await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/changed.*review/i)
  expect(input).toHaveValue('Scout')
  expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled()
  expect(changed).toHaveBeenCalledOnce()
  const refreshed = { ...robot, name: 'Updated by teammate', version: 2 }
  view.rerender(<Harness entities={[refreshed, sensors, actuators, imu, motor]} />)
  expect(screen.getByRole('textbox', { name: 'Robot name' })).toHaveValue('Scout')
  expect(screen.getByText('Current name: Updated by teammate')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
  expect(api.renamePhysicalRobot).toHaveBeenLastCalledWith(
    'p1',
    refreshed,
    'Scout',
    expect.anything()
  )
})

it('deletes in two steps: the concrete line, Keep cancels, Delete robot removes', async () => {
  render(<Harness />)
  expect(screen.queryByText(/other links are retained/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot…' }))
  expect(
    screen.getByText('Delete Rover? Its parts and other links are retained.')
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
  expect(api.deletePhysicalRobot).not.toHaveBeenCalled()
  expect(screen.queryByText(/other links are retained/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot…' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot' }))
  expect(api.deletePhysicalRobot).toHaveBeenCalledWith('p1', robot, expect.anything())
  await waitFor(() => expect(changed).toHaveBeenCalledWith(robot.id))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('blocks duplicate confirmation writes while deletion is pending', async () => {
  const pending = deferred<{ deleted_entity_id: string; retained_part_ids: string[] }>()
  vi.mocked(api.deletePhysicalRobot).mockReturnValue(pending.promise)
  render(<Harness />)
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot…' }))
  const confirm = screen.getByRole('button', { name: 'Delete robot' })
  fireEvent.click(confirm)
  fireEvent.click(confirm)
  expect(api.deletePhysicalRobot).toHaveBeenCalledOnce()
  await act(async () => {
    pending.resolve({ deleted_entity_id: robot.id, retained_part_ids: [] })
  })
  expect(changed).toHaveBeenCalledOnce()
})

it('keeps a deletion failure visible without claiming parts were unassigned', async () => {
  vi.mocked(api.deletePhysicalRobot).mockRejectedValue(
    new ApiError(403, 'forbidden', 'Member access required')
  )
  render(<Harness />)
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot…' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot' }))
  expect(await screen.findByText(/Member access required/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete robot' })).toBeInTheDocument()
  expect(changed).not.toHaveBeenCalled()
})

it('shows a category’s parts and the Guide/Expert line', () => {
  render(<Harness selected={sensors.id} />)
  expect(screen.getByRole('heading', { name: 'Sensors' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reveal Wrist IMU' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Reveal Drive motor' })).not.toBeInTheDocument()
  expect(screen.getByText('Parts assigned to this category appear inside.')).toBeInTheDocument()
  act(() => useSettingsStore.setState({ solMode: 'Expert' }))
  expect(screen.getByText('Assigned parts inside.')).toBeInTheDocument()
  expect(resources.listBenchSessions).not.toHaveBeenCalled()
})

it('reads once per robot and again only after the snapshot changes', async () => {
  const view = render(<Harness />)
  await screen.findByText('Not connected')
  view.rerender(<Harness selected={sensors.id} />)
  view.rerender(<Harness />)
  await screen.findByText('Not connected')
  expect(resources.listBenchSessions).toHaveBeenCalledOnce()
  view.rerender(<Harness entities={[...ENTITIES]} />)
  await waitFor(() => expect(resources.listBenchSessions).toHaveBeenCalledTimes(2))
})

it.each([
  ['connecting', 'Connecting…'],
  ['connected', 'Connected'],
  ['failed', 'Connection failed. Retry from the saved hardware.'],
  ['disconnected', 'Disconnected']
])(
  'renders managed %s state directly from the current graph without claiming packets',
  async (status, label) => {
    const live = {
      ...robot,
      properties: {
        connection: {
          managed_by: 'local_runtime',
          attempt_id: 'attempt',
          status,
          session_id: null,
          error: null
        }
      }
    }
    render(<Harness entities={[live]} />)
    expect(
      within(screen.getByRole('region', { name: 'Connection' })).getByRole('status')
    ).toHaveTextContent(label)
  }
)

it('explains a serial-less USB port binding in the sidebar', async () => {
  vi.mocked(hardwareApi.getHardwareConfig).mockResolvedValue({
    entry_id: 'entry',
    robot_entity_id: robot.id,
    config: {
      schema_version: 1,
      robot_entity_id: robot.id,
      identity: { kind: 'usb_serial', binding: 'usb:port-3-1.2' },
      provenance: {}
    }
  })
  render(<Harness />)
  expect(
    await screen.findByText('identity from the USB port — keep it in this port')
  ).toBeInTheDocument()
})
