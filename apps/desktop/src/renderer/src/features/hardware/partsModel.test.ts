// SOLUSDEV-326 P3: the parts list's groups, counts and order.
import { describe, expect, it } from 'vitest'
import { expectedKeys, groupParts } from './partsModel'
import { device } from './testing/fixtures'
import { machine, part, robot } from './testing/parts'

describe('groupParts', () => {
  it('puts parts under their robot and lone parts under "Not on a robot", with counts', () => {
    const { groups, count } = groupParts(
      {
        robots: [robot('r1', 'Rover arm')],
        parts: [
          part('p1', 'shoulder_pan', { parent_id: 'r1', model: 'STS3215' }),
          part('p2', 'elbow', { parent_id: 'r1', model: 'STS3215' }),
          part('p3', 'motor_driver', { category: 'driver board' })
        ],
        machines: []
      },
      []
    )
    expect(count).toBe(3)
    expect(groups.map((group) => group.title)).toEqual(['Rover arm', 'Not on a robot'])
    expect(groups.map((group) => group.countLabel)).toEqual(['2 parts', '1'])
    expect(groups[0].rows.map((row) => [row.name, row.what, row.robot])).toEqual([
      ['shoulder_pan', 'STS3215', 'Rover arm'],
      ['elbow', 'STS3215', 'Rover arm']
    ])
    expect(groups[1].rows[0]).toMatchObject({ what: 'driver board', robot: null, canAdd: false })
  })

  it('keeps only hardware: a connector part no robot holds is not a robot part', () => {
    const { groups, count } = groupParts(
      {
        robots: [robot('r1', 'Arm'), robot('r2', 'Synced', { origin: 'connector' })],
        parts: [
          part('c1', 'R12', { type: 'component', origin: 'connector' }),
          part('c2', 'gripper.step', { type: 'cad_part', origin: 'connector', parent_id: 'r1' })
        ],
        machines: []
      },
      []
    )
    expect(count).toBe(1)
    expect(groups).toHaveLength(1)
    expect(groups[0].rows.map((row) => row.name)).toEqual(['gripper.step'])
  })

  it('orders robots and parts oldest first, so a new one lands at the end of its group', () => {
    const { groups } = groupParts(
      {
        robots: [
          robot('r2', 'Newer', { created_at: '2026-11-02T00:00:00Z' }),
          robot('r1', 'Older', { created_at: '2026-11-01T00:00:00Z' })
        ],
        parts: [
          part('p2', 'second', { parent_id: 'r1', created_at: '2026-11-04T00:00:00Z' }),
          part('p1', 'first', { parent_id: 'r1', created_at: '2026-11-03T00:00:00Z' })
        ],
        machines: []
      },
      []
    )
    expect(groups.map((group) => group.title)).toEqual(['Older', 'Newer'])
    expect(groups[0].rows.map((row) => row.name)).toEqual(['first', 'second'])
  })

  it('says what is in the graph, and offers Add only where the route takes it', () => {
    const { groups } = groupParts(
      {
        robots: [robot('r1', 'Hidden arm', { in_graph: false }), robot('r2', 'Shown arm')],
        parts: [
          part('p1', 'servo', { parent_id: 'r1', in_graph: false }),
          part('p2', 'lone', { in_graph: false }),
          part('p3', 'lone in', {})
        ],
        machines: []
      },
      []
    )
    const [hidden, shown, lone] = groups
    expect(hidden).toMatchObject({ inGraph: false, canAdd: true })
    expect(shown).toMatchObject({ inGraph: true, canAdd: false })
    // A robot's part moves with its robot (docs/api/hardware.md §1a): no button of its own.
    expect(hidden.rows[0]).toMatchObject({ inGraph: false, canAdd: false })
    expect(lone.rows[0]).toMatchObject({ inGraph: false, canAdd: true })
    expect(lone.rows[1]).toMatchObject({ inGraph: true, canAdd: false })
    expect(lone.canAdd).toBe(false)
  })

  it('derives each status from the device rows, the connection and the machine memory', () => {
    const { groups } = groupParts(
      {
        robots: [
          robot('r1', 'Arm'),
          robot('r2', 'Live', { connection: { status: 'connected' } }),
          robot('r3', 'Plain')
        ],
        parts: [
          part('p1', 'here', { parent_id: 'r1', device_ref: 'usb:A' }),
          part('p2', 'gone', { parent_id: 'r1', device_ref: 'usb:B' }),
          part('p3', 'never', { parent_id: 'r1', device_ref: 'usb:C' }),
          part('p4', 'looking', { parent_id: 'r1', device_ref: 'usb:D' }),
          part('p5', 'live', { parent_id: 'r2' }),
          part('p6', 'bound', {})
        ],
        machines: [
          machine([
            { device_ref: 'usb:A', last_seen: '2026-11-16T00:00:00Z', present: true },
            { device_ref: 'usb:B', last_seen: '2026-11-14T00:00:00Z', present: false }
          ])
        ]
      },
      [
        device('usb:A', { bound_to: 'r1' }),
        device('usb:D', { bound_to: 'r1', state: 'inspecting' }),
        device('usb:E', { bound_to: 'p6' }),
        device('usb:F', { bound_to: 'r3' })
      ]
    )
    const status = Object.fromEntries(
      groups.flatMap((group) => group.rows).map((row) => [row.name, row.status])
    )
    expect(status).toEqual({
      here: { kind: 'connected' },
      gone: { kind: 'last_seen', at: '2026-11-14T00:00:00Z' },
      never: { kind: 'not_connected' },
      looking: { kind: 'identifying' },
      live: { kind: 'connected' },
      bound: { kind: 'connected' }
    })
    // A robot with no parts is a plain connection: it says its own status on the group row.
    expect(groups.find((group) => group.title === 'Plain')?.status).toEqual({ kind: 'streaming' })
    expect(groups.find((group) => group.title === 'Arm')?.status).toBeNull()
  })

  it('is empty with no robots and no parts', () => {
    expect(groupParts({ robots: [], parts: [], machines: [] }, [])).toEqual({
      groups: [],
      count: 0
    })
  })

  it('a device that left while watched is last seen when it left, over the older memory', () => {
    const data = {
      robots: [robot('r1', 'Rover arm')],
      parts: [part('p1', 'named', { parent_id: 'r1', device_ref: 'usb:A' }), part('p2', 'bound')],
      machines: [machine([{ device_ref: 'usb:A', last_seen: '2026-11-14T00:00:00Z' }])]
    }
    const left = [
      device('usb:A', { last_seen: '2026-11-16T10:00:00.000Z' }),
      device('usb:B', { bound_to: 'p2', last_seen: '2026-11-16T10:00:01.000Z' })
    ]
    const { groups } = groupParts(data, [], left)
    expect(groups[0].rows[0].status).toEqual({ kind: 'last_seen', at: '2026-11-16T10:00:00.000Z' })
    expect(groups[1].rows[0].status).toEqual({ kind: 'last_seen', at: '2026-11-16T10:00:01.000Z' })
  })
})

describe('expectedKeys', () => {
  it('numbers the rows that share a source, a name and a what, so no two keys are the same', () => {
    const slot = { name: '', what: 'STS3215', robot_id: 'r1', source: 'Rover arm' }
    const cam = { name: 'wrist_cam', what: 'sensor_msgs/Image', robot_id: null, source: 'arm.yaml' }
    expect(expectedKeys([slot, cam, slot, slot])).toEqual([
      'expected:Rover arm::STS3215:0',
      'expected:arm.yaml:wrist_cam:sensor_msgs/Image:0',
      'expected:Rover arm::STS3215:1',
      'expected:Rover arm::STS3215:2'
    ])
  })
})
