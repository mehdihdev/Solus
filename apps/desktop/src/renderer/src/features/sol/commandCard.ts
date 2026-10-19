// SOLUSDEV-317: presentation helpers for command approval cards
// (docs/wireflows/sol-page.md "Command execution"). PURE and presentation-only:
// the header is read from the server's verbatim rows, the renderer classifies
// nothing, and every value renders as plain text.
import type { PendingConfirmation } from '../../lib/api/solStream'
import type { ConfirmationOutcome } from '../../lib/api/resources'

/** Tools whose card shows the command header, accepts Cmd/Ctrl+Enter and
 *  resumes the turn once approved (code-command-execution.md §5.5). */
export const COMMAND_TOOLS: ReadonlySet<string> = new Set([
  'code.exec',
  'code.process_start',
  'code.run',
  'code.test',
  'code.install',
  'code.create_environment',
  'code.profile_capture'
])

/** Tools whose approved call streams incremental output (§5.4). */
const OUTPUT_TOOLS: ReadonlySet<string> = new Set(['code.exec', 'code.run', 'code.test'])

const RISK_TOKEN = /^[a-z_]{1,32}$/
const SANDBOX_KINDS = ['sandbox-exec', 'landlock']
/** The first JSON string of an argv array, even when the row is a partial chunk. */
const FIRST_ARG = /^\s*\[\s*("(?:[^"\\]|\\.)*")/

export function isCommandTool(tool: string): boolean {
  return COMMAND_TOOLS.has(tool)
}

export function hasCommandOutput(tool: string): boolean {
  return OUTPUT_TOOLS.has(tool)
}

export interface CommandHeader {
  readonly program: string | null
  readonly risks: readonly string[]
  readonly sandboxed: boolean
}

function rowValue(pending: PendingConfirmation, match: (label: string) => boolean): string | null {
  const row = pending.preview.find((r) => match(r.label))
  return row ? (row.after ?? row.before) : null
}

function basename(path: string): string | null {
  const name = path.split('/').filter(Boolean).pop()
  return name ?? null
}

function firstArg(command: string): string | null {
  const match = FIRST_ARG.exec(command)
  if (!match) return null
  try {
    const value: unknown = JSON.parse(match[1])
    return typeof value === 'string' ? value : null
  } catch {
    return null
  }
}

function programOf(pending: PendingConfirmation): string | null {
  const program = rowValue(pending, (label) => label === 'program')
  if (program) return basename(program)
  const command = rowValue(pending, (label) => label === 'command' || label === 'command 1/1')
  const chunk = command ?? rowValue(pending, (label) => /^command 1\/\d+$/.test(label))
  const argv0 = chunk ? firstArg(chunk) : null
  return argv0 ? basename(argv0) : null
}

function risksOf(pending: PendingConfirmation): string[] {
  const risk = rowValue(pending, (label) => label === 'risk')
  if (!risk) return []
  return risk
    .split(',')
    .map((token) => token.trim())
    .filter((token) => RISK_TOKEN.test(token))
}

/** The card header for a command tool; null for every other card. */
export function commandHeader(pending: PendingConfirmation): CommandHeader | null {
  if (!isCommandTool(pending.tool)) return null
  const sandbox = rowValue(pending, (label) => label === 'sandbox') ?? ''
  return {
    program: programOf(pending),
    risks: risksOf(pending),
    sandboxed: SANDBOX_KINDS.some((kind) => sandbox.startsWith(kind))
  }
}

const REASON_CAP = 200

/** The exit status shown under a finished command's retained output. A command
 *  that ran and failed arrives as `{ok: false, exit_code: N}`, so the exit code
 *  wins over `ok`; only `ok: false` with no exit code is a refusal (§7a). */
export function commandExitStatus(outcome: ConfirmationOutcome): string {
  const value = outcome.value ?? {}
  if (value.timed_out === true) return 'timed out'
  if (typeof value.exit_code === 'number') return `exited ${value.exit_code}`
  if (value.ok === false) {
    const reason = typeof value.reason === 'string' ? value.reason : 'not run'
    return `refused: ${reason.slice(0, REASON_CAP)}`
  }
  return 'finished'
}
