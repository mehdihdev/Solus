// Pure presentation rules for the Local Connections section (SOLUSDEV-72).
// One honesty contract, testable directly: render exactly what the backend
// claims — never a guessed board, never a capability implied from a bare
// connection, never an invented error explanation.
import { getDesktopPlatform } from '../../../lib/desktopBridge'
import { ApiError } from '../../../lib/api/envelope.types'
import type {
  BenchDevice,
  BenchSession,
  BenchSimulatorKind,
  BridgeStatus,
  GazeboSimConfig,
  LocalTool,
  McapReplayConfig,
  MujocoSimConfig
} from '../../../lib/api/resources'

const SIMULATOR_NAMES: Record<BenchSimulatorKind, string> = {
  mujoco: 'MuJoCo',
  gazebo: 'Gazebo',
  isaac: 'Isaac Sim',
  'mcap-replay': 'MCAP replay'
}

export function simulatorName(kind: BenchSimulatorKind): string {
  return SIMULATOR_NAMES[kind]
}

const SIMULATOR_MARKS: Record<BenchSimulatorKind, string> = {
  mujoco: 'Mu',
  gazebo: 'Ga',
  isaac: 'Is',
  'mcap-replay': 'MC'
}

/** The config a simulator start sends (`POST /bench/sessions`, mode sim). */
export type SimStartConfig = MujocoSimConfig | GazeboSimConfig | McapReplayConfig

/** The two-letter mark a simulator row leads with (no vendor logo shipped). */
export function simulatorMark(kind: BenchSimulatorKind): string {
  return SIMULATOR_MARKS[kind]
}

/** Preserve a definition-provided tentative hint without deriving a board identity. */
export function deviceTitle(device: BenchDevice): string {
  if (device.headline) return device.headline
  if (device.board_class === 'usb_bridge') return 'something on USB'
  return device.board ?? 'Unknown device'
}

/** A session the user can see and stop: `starting` counts — the backend's
 *  own `status=active` filter includes it. */
function isRunning(session: BenchSession): boolean {
  return session.status === 'active' || session.status === 'starting'
}

export function sessionsForSimulator(
  sessions: readonly BenchSession[],
  kind: BenchSimulatorKind
): BenchSession[] {
  return sessions.filter((s) => s.mode === 'sim' && s.provider === kind && isRunning(s))
}

/** Real sessions belonging to a device row. An explicit pick wins: a session
 *  started with a confirmed `device_path` belongs to the row carrying that
 *  path (or its stable by_id alias), even when serials are shared. Otherwise
 *  match on non-null serial equality — never on nothing. */
export function sessionsForDevice(
  sessions: readonly BenchSession[],
  device: BenchDevice
): BenchSession[] {
  return sessions.filter((s) => {
    if (s.mode !== 'real' || !isRunning(s) || !s.device) return false
    if (s.device.device_path !== null) {
      return (
        s.device.device_path === device.device_path || s.device.device_path === device.by_id_path
      )
    }
    return s.device.serial_number !== null && s.device.serial_number === device.serial_number
  })
}

/** Active sessions no simulator or device row will render (e.g. a real
 *  session whose device was unplugged) — listed separately so every session
 *  stays visible and stoppable. */
export function unmatchedSessions(
  sessions: readonly BenchSession[],
  simulators: readonly { kind: BenchSimulatorKind }[],
  devices: readonly BenchDevice[]
): BenchSession[] {
  const matched = new Set<string>()
  for (const sim of simulators) {
    for (const s of sessionsForSimulator(sessions, sim.kind)) matched.add(s.id)
  }
  for (const d of devices) {
    for (const s of sessionsForDevice(sessions, d)) matched.add(s.id)
  }
  return sessions.filter((s) => isRunning(s) && !matched.has(s.id))
}

/** One honest line per tool: companion state first, then the tool's server.
 *  A connected companion with no server for this tool means nothing is
 *  callable — never imply function from the connection alone. */
const PLATFORM_NAMES: Record<string, string> = { linux: 'Linux', darwin: 'macOS', win32: 'Windows' }

export function platformUnavailableReason(
  tool: LocalTool,
  platform: string | null = getDesktopPlatform()
): string | null {
  if (tool.supported_platforms == null) return null
  if (tool.supported_platforms.length === 0) return 'Platform availability is unavailable'
  if (!platform || !PLATFORM_NAMES[platform])
    return 'Open the desktop app to check platform availability'
  if (tool.supported_platforms.some((supported) => supported === platform)) return null
  return `${tool.display_name} is not available on ${PLATFORM_NAMES[platform]}`
}

/** Existing bridge details encode an unavailable host without extending the protocol. */
export function isPlatformUnavailableDetail(detail: string | null): boolean {
  return (
    detail !== null &&
    /^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,79} is not available on (Linux|macOS|Windows|this operating system)$/.test(
      detail
    )
  )
}

export function toolStatusText(
  tool: LocalTool,
  bridge: BridgeStatus | null,
  platform: string | null = getDesktopPlatform()
): string {
  const unavailable = platformUnavailableReason(tool, platform)
  if (unavailable) return unavailable
  if (!bridge?.connected) return 'Companion offline'
  const server = bridge.servers.find((s) => s.name === tool.type)
  if (!server) return 'Connected — no tools callable yet'
  if (server.state === 'ready') {
    if (server.license_state === 'bring_your_license') return 'Server ready — license key required'
    if (server.license_state === 'upgrade_required') return 'Server ready — plan upgrade required'
    return 'Server ready'
  }
  const detail = server.detail ? ` — ${server.detail}` : ''
  return `Server ${server.state.replace(/_/g, ' ')}${detail}`
}

/** Best discriminator per 409 candidate: path, then by_id alias, then serial.
 *  Details are untrusted — anything unrecognisable is dropped, not rendered. */
function ambiguityCandidates(details: readonly unknown[] | undefined): string {
  const names = (details ?? []).flatMap((entry) => {
    if (typeof entry === 'string') return [entry]
    if (entry && typeof entry === 'object') {
      const c = entry as Record<string, unknown>
      const pick = c.device_path ?? c.by_id_path ?? c.serial_number
      if (typeof pick === 'string') return [pick]
    }
    return []
  })
  return names.length > 0 ? ` Candidates: ${names.join(', ')}.` : ''
}

/** Session-start failures, mapped to actionable copy. Server reasons pass
 *  through verbatim; only pure transport failures get local wording. */
export function connectErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'too_many_sessions') {
      return 'Session limit reached — stop an active session first.'
    }
    if (error.code === 'device_ambiguous') {
      return `Several devices match — confirm the exact port and try again.${ambiguityCandidates(error.details)}`
    }
    return error.message
  }
  return "Couldn't reach the Solus API — try again once you're back online."
}
