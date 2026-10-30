// Shared test fixtures for teleoperation UI tests.
import type { Teleop, TeleopPreview } from '../../lib/api/resources'
import type { RobotPanelInfo } from './robotGrouping'

export const LEADER: RobotPanelInfo = {
  robotId: 'r1',
  sessionId: 's1',
  name: 'lerobot leader',
  deviceIds: ['usb:A/1']
}
export const FOLLOWER: RobotPanelInfo = {
  robotId: 'r2',
  sessionId: 's2',
  name: 'lerobot follower',
  deviceIds: ['usb:B/1']
}

export function previewFixture(over: Partial<TeleopPreview> = {}): TeleopPreview {
  return {
    preview_id: 'prev-1',
    expires_at: '2026-10-30T00:00:30Z',
    leader: { session_id: 's1', label: 'Robot lerobot leader (usb:A)' },
    follower: { session_id: 's2', label: 'Robot lerobot follower (usb:B)' },
    ready: true,
    blockers: [],
    pairs: [
      {
        address: 1,
        leader_signal: 'shoulder_pan',
        follower_signal: 'shoulder_pan',
        unit: 'deg',
        leader_value: 10,
        follower_value: 12.5,
        delta: 2.5,
        within_tolerance: true
      }
    ],
    tolerance: { deg: 15, '%': 20 },
    ...over
  }
}

export function teleopFixture(over: Partial<Teleop> = {}): Teleop {
  return {
    id: 't1',
    state: 'running',
    leader: { session_id: 's1', label: 'Robot lerobot leader (usb:A)' },
    follower: { session_id: 's2', label: 'Robot lerobot follower (usb:B)' },
    rate_hz: 30,
    started_at: '2026-10-30T00:00:00Z',
    stopped_at: null,
    stop_reason: null,
    pairs: [],
    ...over
  }
}
