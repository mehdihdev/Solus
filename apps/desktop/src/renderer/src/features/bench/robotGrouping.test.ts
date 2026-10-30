import { describe, it, expect } from 'vitest'
import type { BenchSession } from '../../lib/api/resources'
import { defaultTeleopPair, groupRobotSessions } from './robotGrouping'

function session(id: string, label: string, robot: string | null, ids: string[]): BenchSession {
  return {
    id,
    mode: 'real',
    provider: 'robot',
    status: 'active',
    link: 'streaming',
    label,
    created_at: '2026-10-30T00:00:00Z',
    ended_at: null,
    device: robot
      ? { serial_number: null, device_path: null, baud: null, robot_entity_id: robot }
      : null,
    device_ids: ids,
    counts: { ingested: 0, unresolved: 0 },
    last_summary: null
  }
}
const FOLLOWER = session('s2', 'Robot lerobot follower (usb:B)', 'r2', ['usb:B/1'])
const LEADER = session('s1', 'Robot lerobot leader (usb:A)', 'r1', ['usb:A/1'])
const SIM = session('s3', 'MuJoCo demo', null, ['demo/rod'])

describe('groupRobotSessions', () => {
  it('makes one panel per robot session, ordered by robot name', () => {
    const { robots } = groupRobotSessions([FOLLOWER, SIM, LEADER])
    expect(robots.map((r) => [r.name, r.robotId, r.sessionId])).toEqual([
      ['lerobot follower', 'r2', 's2'],
      ['lerobot leader', 'r1', 's1']
    ])
    expect(robots[0].deviceIds).toEqual(['usb:B/1'])
  })
  it('keeps the order stable regardless of input order', () => {
    const a = groupRobotSessions([FOLLOWER, LEADER]).robots.map((r) => r.sessionId)
    const b = groupRobotSessions([LEADER, FOLLOWER]).robots.map((r) => r.sessionId)
    expect(a).toEqual(b)
  })
  it('leaves non-robot devices and external devices in the fallback', () => {
    const { otherDeviceIds } = groupRobotSessions([LEADER, SIM], ['ext/1', 'usb:A/1'])
    expect(otherDeviceIds).toEqual(['demo/rod', 'ext/1'])
  })
  it('handles null sessions and falls back to the label for the name', () => {
    expect(groupRobotSessions(null).robots).toEqual([])
    const odd = session('s9', 'Weird label', 'r9', [])
    expect(groupRobotSessions([odd]).robots[0].name).toBe('Weird label')
  })
  it('skips ended robot sessions', () => {
    const ended = { ...LEADER, status: 'ended' as const }
    expect(groupRobotSessions([ended]).robots).toEqual([])
  })
})

describe('defaultTeleopPair', () => {
  const robots = groupRobotSessions([FOLLOWER, LEADER]).robots
  it('picks names containing leader and follower', () => {
    expect(defaultTeleopPair(robots)).toEqual({ leader: 's1', follower: 's2' })
  })
  it('falls back to the first two robots', () => {
    const plain = groupRobotSessions([
      session('a', 'Robot alpha (x)', 'ra', []),
      session('b', 'Robot beta (y)', 'rb', [])
    ]).robots
    expect(defaultTeleopPair(plain)).toEqual({ leader: 'a', follower: 'b' })
  })
  it('returns null with fewer than two robots', () => {
    expect(defaultTeleopPair(robots.slice(0, 1))).toBeNull()
  })
})
