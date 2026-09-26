// Pure rules behind a device card (SOLUSDEV-250 P3): which detected devices
// are still pending, the one sentence a card reads, the single question it
// asks, the default Add body, and where a rail-confirmed robot lands.
// Everything the user reads comes from the wire — nothing here names a product.
import type {
  AcceptedRow,
  ConfirmOut,
  DetectedDeviceOut,
  HardwareSuggestion,
  ProposalOut
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { STEP_X, STEP_Y } from '../navigation/layout'
import { detectedTitle, identityNote, proposalHeadline, robotIdFromMessage } from './detected'

export type DeviceCardStatus =
  | 'proposing'
  | 'proposed'
  | 'silent'
  | 'failed'
  | 'confirming'
  | 'done'

export interface DeviceCardState {
  ref: string
  device: DetectedDeviceOut
  status: DeviceCardStatus
  proposal: ProposalOut | null
  /** The backend's message, verbatim. */
  error: string | null
  /** The robot a 409 named — the card offers "Add to that robot instead". */
  conflictRobotId: string | null
  result: ConfirmOut | null
  attempts: number
}

export type CardQuestion =
  | { kind: 'name' }
  | { kind: 'choose'; question: string; options: { configId: string; label: string }[] }
  | { kind: 'suggest'; suggestion: HardwareSuggestion }

const LOOKING = 'looking at what answers…'
const AMBIGUOUS_NOTE = 'no unique identity yet — reconnect it to verify'
export { AMBIGUOUS_NOTE }

/** A part keyed `<device ref>/<address>` binds its device. The ref never
 *  contains '/', so the prefix before the FIRST slash is the ref. */
export function boundDeviceRefs(entities: readonly Entity[] | null): Set<string> {
  const refs = new Set<string>()
  for (const entity of entities ?? []) {
    // Manual and .solus entities carry no source key on the wire.
    const key = entity.source_key ?? ''
    const slash = key.indexOf('/')
    if (slash > 0) refs.add(key.slice(0, slash))
  }
  return refs
}

export function pendingDevices(
  devices: readonly DetectedDeviceOut[],
  entities: readonly Entity[] | null,
  dismissed: ReadonlySet<string>
): DetectedDeviceOut[] {
  const bound = boundDeviceRefs(entities)
  return devices.filter(
    (device) =>
      device.device_ref !== null &&
      !bound.has(device.device_ref) &&
      !dismissed.has(device.device_ref)
  )
}

export function cardSentence(
  device: DetectedDeviceOut,
  proposal: ProposalOut | null,
  status: DeviceCardStatus
): string {
  if (proposal) return proposalHeadline(proposal)
  const title = detectedTitle(device)
  const tail = status === 'proposing' ? LOOKING : identityNote(device)
  return tail ? `${title} · ${tail}` : title
}

/** A small mono glyph per driver family: a line stream, a bus, unknown. */
export function cardGlyph(proposal: ProposalOut | null): string {
  if (!proposal?.driver_id) return '?'
  return proposal.stream ? '⌇' : '⛓'
}

/** Guide mode's one muted line: the proposal's distinct evidence notes, verbatim, at most two. */
export function evidenceNotes(proposal: ProposalOut): string {
  const notes = proposal.evidence
    .map((match) => match.evidence.note)
    .filter((note): note is string => typeof note === 'string' && note !== '')
  return [...new Set(notes)].slice(0, 2).join(' · ')
}

export function cardQuestion(proposal: ProposalOut): CardQuestion {
  const question = proposal.disambiguation
  if (question && question.options.length === 2) {
    const options = question.options.flatMap((configId) => {
      const match = proposal.repo_matches.find((m) => m.config_id === configId)
      return match ? [{ configId, label: match.label }] : []
    })
    if (options.length === 2) return { kind: 'choose', question: question.question, options }
  }
  const suggestion = proposal.suggestions?.[0]
  if (suggestion) return { kind: 'suggest', suggestion }
  return { kind: 'name' }
}

/** Every row, nothing hidden or rejected — channel names are edited later in
 *  the sidebar / Live Bench. A line stream's channels are readings. */
export function defaultAccepted(proposal: ProposalOut): AcceptedRow[] {
  const category = proposal.stream ? 'sensors' : 'actuators'
  return proposal.rows.map((row) => ({
    row_id: row.id,
    function_name: row.proposed_function ?? null,
    category
  }))
}

/** A 409's sentence, verbatim, with the robot uuid it names replaced by the
 *  robot's name when `robots` has it — an id is never shown on purpose. */
export function conflictText(error: string, robots: readonly Entity[]): string {
  const id = robotIdFromMessage(error)
  const name = id === null ? undefined : robots.find((robot) => robot.id === id)?.name
  return id !== null && name ? error.replace(id, name) : error
}

/** Where a robot confirmed from the canvas-edge rail lands: near the rail, clear of the origin. */
export function placementNearRail(): Point {
  return { x: 2 * STEP_X, y: -STEP_Y }
}

/** Explicit transport evidence is sufficient to save a connection, never a protocol. */
export function connectionOnly(proposal: ProposalOut | null): boolean {
  return (
    proposal?.identity?.kind === 'usb_serial' &&
    proposal.driver_id === null &&
    proposal.rows.length === 0 &&
    Object.keys(proposal.params).length === 0 &&
    !proposal.stream
  )
}
