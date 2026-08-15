// RBT-03: the proposal model the recognition surface renders. Everything upstream
// (RBT-01 passive probes, RBT-02 firmware idioms, RBT-04 active runs) produces
// EVIDENCE; a row here is a proposal the user confirms — never an assertion.

export type EvidenceKind = 'bus_enumeration' | 'firmware_symbol' | 'telemetry_channel'

export interface ProposalEvidence {
  readonly kind: EvidenceKind
  /** What matched — a model register, a firmware symbol, a stream shape. */
  readonly value: string
  /** The honesty note that travels with the evidence (CTR-08 style). */
  readonly note: string
  /** file:line, bus address, port — where this evidence came from. */
  readonly provenance: string
}

export interface MappingProposal {
  /** Stable row id: the channel/motor being mapped (e.g. "ttyUSB0/id:3", "ch2"). */
  readonly id: string
  /** What the hardware side is, as honestly as it is known. */
  readonly subject: string
  /** The proposed function (joint/role), or null when inference has NOTHING — unknown. */
  readonly proposedFunction: string | null
  /** Calibrated confidence 0..1, or null for unknown rows. */
  readonly confidence: number | null
  readonly evidence: readonly ProposalEvidence[]
}

export type Decision =
  | { readonly kind: 'accept' }
  | { readonly kind: 'reject' }
  /** The user named or renamed the function — tier 3's primary flow. */
  | { readonly kind: 'edit'; readonly functionName: string }

export type RowStatus = 'proposed' | 'unknown' | 'accepted' | 'rejected' | 'edited'
