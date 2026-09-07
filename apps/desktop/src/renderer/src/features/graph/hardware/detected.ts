// Pure rules for the Detected flow (SOLUSDEV-248 R2): device titles at the
// level honestly known, proposal rows → RecognitionPanel proposals, and the
// confirm body built ONLY from rows the user accepted or named.
import type {
  AcceptedRow,
  DetectedDeviceOut,
  ProposalRowOut,
  RobotCategory
} from '../../../lib/api/hardware'
import type {
  Decision,
  MappingProposal
} from '../../../widgets/livebench/recognition/proposals.types'

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

/** A transport-level device is named for its bridge only — never a guessed board
 *  (the same wording as `deviceTitle` for a USB bridge). */
export function detectedTitle(device: DetectedDeviceOut): string {
  if (device.level !== 'transport') return device.board ?? 'Unknown device'
  if (device.transport === 'usb_serial') return 'USB-serial bridge — MCU unknown'
  return `${device.transport} device — unknown`
}

function hex4(value: number): string {
  return value.toString(16).padStart(4, '0')
}

/** The `transport:binding` identity, vid:pid and last path — informational only. */
export function detectedIdentity(device: DetectedDeviceOut): string {
  const parts = [device.device_ref ?? 'no serial — unverified after replug']
  if (device.vid != null && device.pid != null)
    parts.push(`${hex4(device.vid)}:${hex4(device.pid)}`)
  if (device.last_seen_path) parts.push(device.last_seen_path)
  return parts.join(' · ')
}

export function toMappingProposal(row: ProposalRowOut): MappingProposal {
  return {
    id: row.id,
    subject: row.subject,
    proposedFunction: row.proposed_function,
    confidence: row.confidence,
    evidence: row.evidence.map((match) => ({
      kind: match.modality,
      value: String(match.evidence.value ?? ''),
      note: String(match.evidence.note ?? ''),
      provenance: match.source_ref.external_ref ?? ''
    }))
  }
}

/** Only rows the user accepted or named; a rejected or untouched row is never sent. */
export function acceptedRows(
  rows: readonly ProposalRowOut[],
  decisions: Readonly<Record<string, Decision | undefined>>,
  categories: Readonly<Record<string, RobotCategory | undefined>>
): AcceptedRow[] {
  return rows.flatMap((row) => {
    const decision = decisions[row.id]
    if (!decision || decision.kind === 'reject') return []
    const name = decision.kind === 'edit' ? decision.functionName : row.proposed_function
    return [
      {
        row_id: row.id,
        function_name: name ?? undefined,
        category: categories[row.id] ?? 'actuators'
      }
    ]
  })
}

/** The robot id a 409 names ("… is already part of robot <uuid> …"), if any. */
export function robotIdFromMessage(message: string): string | null {
  return UUID_RE.exec(message)?.[0] ?? null
}

export function hardwareErrorText(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}
