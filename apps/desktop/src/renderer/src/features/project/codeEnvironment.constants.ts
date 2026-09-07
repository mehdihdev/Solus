// The Code environment row's pure words and decisions (SOLUSDEV-250 / I3).
// Free of React so the row, the modal and the tests share one truth: which
// state to show, and that every unknown is called unknown rather than guessed.
import type { CodeEnvironmentView } from '../../lib/api/resources.codeenv'
import type { LocalFolderStatus } from './localFolder.constants'
import { API_UNREACHABLE_NOTE, COMPANION_OFFLINE_NOTE } from './localFolder.constants'

/** The folder watcher drives real changes; a slow refresh keeps the row honest. */
export const CODE_ENVIRONMENT_POLL_MS = 30_000
/** Each modal section enters this much after the one before it. */
export const SECTION_STAGGER_MS = 30

export const CODE_SERVER_NOT_RUNNING_NOTE = 'code server not running'
export const NOT_PROBED_NOTE = 'not probed yet'
export const NO_PYTHON_NOTE = 'no Python found'
export const NO_VENV_NOTE = 'no virtual environment'
export const NOT_FOUND_NOTE = 'not found'
export const NO_REQUIREMENTS_TEXT = 'No requirement files found in the linked folder.'
export const SOL_SETUP_MESSAGE =
  'Set up my Python environment from the proposal: create the environments, ' +
  'install the requirements, then run the tests.'

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

/** The row's status line, in order of what blocks the next thing: no API, no
 *  companion, no code server, no probe — then the live summary. */
export function codeEnvironmentStatus(
  view: CodeEnvironmentView | null,
  status: LocalFolderStatus
): string {
  if (!view) return status === 'offline' ? API_UNREACHABLE_NOTE : 'Loading…'
  if (!view.bridge.connected) return COMPANION_OFFLINE_NOTE
  if (!view.bridge.code_server) return CODE_SERVER_NOT_RUNNING_NOTE
  if (!view.probe) return NOT_PROBED_NOTE
  const python = view.probe.python?.version ?? NO_PYTHON_NOTE
  const venv = view.probe.venv?.path ?? NO_VENV_NOTE
  return `${python} · ${venv} · ${plural(view.requirements.count, 'requirement')}`
}

/** The second, red line: how many conflicts, and whether a split is proposed.
 *  Null when there is nothing to warn about. */
export function conflictLine(view: CodeEnvironmentView | null): string | null {
  const count = view?.conflicts.length ?? 0
  if (count === 0) return null
  const base = plural(count, 'dependency conflict')
  return view?.proposal?.split ? `${base} — split proposed` : base
}

/** The project's `local` source linked on THIS machine, or null. */
export function localSourceForMachine<T extends { type: string; config: Record<string, unknown> }>(
  sources: readonly T[],
  machineId: string | null
): T | null {
  if (!machineId) return null
  return sources.find((s) => s.type === 'local' && s.config.machine_id === machineId) ?? null
}

export interface EvidencePin {
  specifier: string
  source_file: string
}

function isPin(value: unknown): value is EvidencePin {
  if (typeof value !== 'object' || value === null) return false
  const pin = value as Record<string, unknown>
  return typeof pin.specifier === 'string' && typeof pin.source_file === 'string'
}

/** The pins a PinConflictChecker warning carries under `evidence.pins` —
 *  `[{specifier, source_file}]`. Anything else in the evidence is left alone;
 *  a malformed entry is dropped, never rendered as something it is not. */
export function evidencePins(evidence: Record<string, unknown>): EvidencePin[] {
  const pins = evidence.pins
  return Array.isArray(pins) ? pins.filter(isPin) : []
}
