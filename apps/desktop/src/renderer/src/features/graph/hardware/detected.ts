// Pure copy rules for detected devices (SOLUSDEV-248 R2, SOLUSDEV-250 P3):
// titles at the level honestly known, tone as a label, the identity note, and
// the backend's words kept verbatim. The card's own rules live in deviceCard.ts.
import { ApiError } from '../../../lib/api/envelope.types'
import type { DetectedDeviceOut, ProposalOut, ProposalTone } from '../../../lib/api/hardware'

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

const SOMETHING_ON_USB = 'something on USB'
const TONE_LABELS: Record<ProposalTone, string> = {
  looks_like: 'Looks like',
  probably: 'Probably',
  something: 'Something on USB'
}
const PORT_POSITION_NOTE = 'identity from the USB port — keep it in this port'

/** The backend's headline when it sent one; else a transport-level device is
 *  named for what we can honestly see — never a guessed board, never a verdict
 *  (the same wording as `deviceTitle` for a USB bridge). */
export function detectedTitle(device: DetectedDeviceOut): string {
  if (device.headline) return device.headline
  if (device.level !== 'transport') return device.board ?? 'Unknown device'
  if (device.transport === 'usb_serial') return SOMETHING_ON_USB
  return `${device.transport} device — unknown`
}

export function toneLabel(tone: ProposalTone): string {
  return TONE_LABELS[tone]
}

/** Tone then sentence — unless the sentence already opens with the tone or the
 *  wire headline (the backend leads a streamed proposal with the headline, and
 *  "Something on USB · something on USB · …" is the double the rule prevents). */
export function proposalHeadline(proposal: ProposalOut): string {
  const label = toneLabel(proposal.tone ?? 'something')
  const { summary } = proposal
  const lead = summary.toLowerCase()
  const opens = (text: string | null | undefined): boolean =>
    !!text && lead.startsWith(text.toLowerCase())
  if (opens(label)) return summary
  if (opens(proposal.headline))
    return proposal.tone === 'something' ? summary : `${label} ${summary}`
  return `${label} · ${summary}`
}

/** A port-position identity only holds while the device stays in that port. */
export function identityNote(device: DetectedDeviceOut): string {
  return device.identity_basis === 'port_position' ? PORT_POSITION_NOTE : ''
}

/** The robot id a 409 names ("… is already part of robot <uuid> …"), if any. */
export function robotIdFromMessage(message: string): string | null {
  return UUID_RE.exec(message)?.[0] ?? null
}

export function hardwareErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 404)
    return 'This hardware item is no longer available. Reload to review the current project.'
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    ['version_conflict', 'config_conflict'].includes(error.code)
  )
    return 'The saved hardware changed. Reload to review the current version before retrying.'

  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}
