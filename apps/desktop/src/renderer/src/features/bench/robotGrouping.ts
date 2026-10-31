// Groups active bench sessions into per-robot panels (teleoperation wireflow).
// A robot panel is a session that carries `robot_entity_id` (on the session, SOLUSDEV-321,
// or in its device echo).
import type { BenchSession } from '../../lib/api/resources'

export interface RobotPanelInfo {
  robotId: string
  sessionId: string
  name: string
  deviceIds: string[]
}

export interface GroupedSessions {
  robots: RobotPanelInfo[]
  otherDeviceIds: string[]
}

const LABEL_NAME = /^Robot (.+?) \([^)]*\)$/

export function robotNameFromLabel(label: string): string {
  return LABEL_NAME.exec(label)?.[1] ?? label
}

export function groupRobotSessions(
  sessions: readonly BenchSession[] | null,
  externalDeviceIds: readonly string[] = []
): GroupedSessions {
  const robots: RobotPanelInfo[] = []
  const robotDevices = new Set<string>()
  const others: string[] = []
  for (const session of sessions ?? []) {
    const robotId = session.robot_entity_id ?? session.device?.robot_entity_id
    if (robotId && session.status !== 'ended') {
      session.device_ids.forEach((id) => robotDevices.add(id))
      robots.push({
        robotId,
        sessionId: session.id,
        name: robotNameFromLabel(session.label),
        deviceIds: session.device_ids
      })
    } else {
      others.push(...session.device_ids)
    }
  }
  robots.sort((a, b) => a.name.localeCompare(b.name) || a.sessionId.localeCompare(b.sessionId))
  const otherDeviceIds = [...new Set([...others, ...externalDeviceIds])].filter(
    (id) => !robotDevices.has(id)
  )
  return { robots, otherDeviceIds }
}

export function defaultTeleopPair(
  robots: readonly RobotPanelInfo[]
): { leader: string; follower: string } | null {
  if (robots.length < 2) return null
  const named = (word: string): RobotPanelInfo | undefined =>
    robots.find((r) => r.name.toLowerCase().includes(word))
  const leader = named('leader')
  const follower = named('follower')
  if (leader && follower && leader !== follower) {
    return { leader: leader.sessionId, follower: follower.sessionId }
  }
  return { leader: robots[0].sessionId, follower: robots[1].sessionId }
}
