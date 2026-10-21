// SOLUSDEV-317 — typed clients for SOL command execution
// (docs/api/code-command-execution.md §6 and code-environment.md "Incremental
// command output"). Hand-typed: the regenerated schema.ts declares these
// routes' 200 bodies as `unknown` (the routes return plain dicts). Every answer
// crosses a process boundary from the user's machine, so rows are narrowed
// defensively and malformed entries are dropped rather than rendered.
import { api, type ApiClient } from './client'

const seg = encodeURIComponent

export type OutputStream = 'stdout' | 'stderr'

const isStream = (value: unknown): value is OutputStream => value === 'stdout' || value === 'stderr'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

// ---- an approved command's incremental output ---------------------------

export interface ConfirmationOutputChunk {
  readonly sequence: number
  readonly stream: OutputStream
  readonly text: string
}

export interface ConfirmationOutput {
  readonly chunks: readonly ConfirmationOutputChunk[]
  readonly cursor: number
  readonly complete: boolean
  readonly truncated: boolean
}

function toConfirmationChunk(value: unknown): ConfirmationOutputChunk[] {
  if (!isRecord(value)) return []
  const { sequence, stream, text } = value
  if (typeof sequence !== 'number' || !isStream(stream) || typeof text !== 'string') return []
  return [{ sequence, stream, text }]
}

/** GET …/sol/confirmations/{id}/output?cursor= — progress of an approved run. */
export async function getConfirmationOutput(
  projectId: string,
  confirmationId: string,
  cursor: number,
  client: ApiClient = api
): Promise<ConfirmationOutput> {
  const raw = await client.request<Record<string, unknown>>(
    `/projects/${seg(projectId)}/sol/confirmations/${seg(confirmationId)}/output?cursor=${cursor}`
  )
  return {
    chunks: Array.isArray(raw.chunks) ? raw.chunks.flatMap(toConfirmationChunk) : [],
    cursor: typeof raw.cursor === 'number' ? raw.cursor : cursor,
    complete: raw.complete === true,
    truncated: raw.truncated === true
  }
}

// ---- long-running processes (the Running processes strip) ----------------

export type CodeProcessState = 'running' | 'exited' | 'stopped' | 'timed_out' | 'failed_to_start'

const PROCESS_STATES: ReadonlySet<string> = new Set([
  'running',
  'exited',
  'stopped',
  'timed_out',
  'failed_to_start'
])

export interface CodeProcess {
  readonly process_id: string
  readonly name: string | null
  readonly argv: readonly string[]
  readonly cwd: string
  readonly state: CodeProcessState
  readonly pid: number | null
  readonly exit_code: number | null
  readonly started_at: string
  readonly ended_at: string | null
  readonly sandbox: string | null
  /** §11.1: attached to a Solus-owned pseudo-terminal. */
  readonly interactive: boolean
  /** True only for an interactive, running process the server sees asking. */
  readonly awaiting_input: boolean
  /** Increments with each newly detected prompt (0 = none yet). */
  readonly prompt_seq: number
  /** The last lines the program printed — untrusted machine text. */
  readonly prompt_tail: string
}

export interface CodeProcessList {
  readonly bridge: { readonly connected: boolean }
  readonly processes: readonly CodeProcess[]
}

const textOrNull = (value: unknown): string | null => (typeof value === 'string' ? value : null)
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' ? value : null)

/** Client ceiling on a prompt tail (the server caps it at 1024 chars). */
export const MAX_PROMPT_TAIL_CHARS = 1024

interface InteractiveFields {
  readonly interactive: boolean
  readonly awaiting_input: boolean
  readonly prompt_seq: number
  readonly prompt_tail: string
}

/** §11.1 fields, narrowed: anything malformed reads as "not waiting". */
function interactiveFields(value: Record<string, unknown>, state: string): InteractiveFields {
  const interactive = value.interactive === true
  const seq = value.prompt_seq
  const tail = value.prompt_tail
  return {
    interactive,
    awaiting_input: interactive && state === 'running' && value.awaiting_input === true,
    prompt_seq: typeof seq === 'number' && Number.isSafeInteger(seq) && seq > 0 ? seq : 0,
    prompt_tail: typeof tail === 'string' ? tail.slice(-MAX_PROMPT_TAIL_CHARS) : ''
  }
}

function toCodeProcess(value: unknown): CodeProcess[] {
  if (!isRecord(value)) return []
  const { process_id: id, argv, state, started_at: startedAt } = value
  if (typeof id !== 'string' || typeof state !== 'string' || !PROCESS_STATES.has(state)) return []
  if (!Array.isArray(argv) || !argv.every((arg) => typeof arg === 'string')) return []
  if (typeof startedAt !== 'string') return []
  return [
    {
      process_id: id,
      name: textOrNull(value.name),
      argv: argv as string[],
      cwd: textOrNull(value.cwd) ?? '.',
      state: state as CodeProcessState,
      pid: numberOrNull(value.pid),
      exit_code: numberOrNull(value.exit_code),
      started_at: startedAt,
      ended_at: textOrNull(value.ended_at),
      sandbox: textOrNull(value.sandbox),
      ...interactiveFields(value, state)
    }
  ]
}

/** GET …/code/processes?machine_id= — offline answers `processes: []`. */
export async function listCodeProcesses(
  projectId: string,
  machineId: string,
  client: ApiClient = api
): Promise<CodeProcessList> {
  const raw = await client.request<Record<string, unknown>>(
    `/projects/${seg(projectId)}/code/processes?machine_id=${seg(machineId)}`
  )
  const bridge = isRecord(raw.bridge) ? raw.bridge : {}
  return {
    bridge: { connected: bridge.connected === true },
    processes: Array.isArray(raw.processes) ? raw.processes.flatMap(toCodeProcess) : []
  }
}

export interface ProcessOutputChunk {
  readonly seq: number
  readonly stream: OutputStream
  readonly text: string
}

export interface ProcessOutput {
  readonly chunks: readonly ProcessOutputChunk[]
  readonly cursor: number
  readonly truncated: boolean
}

function toProcessChunk(value: unknown): ProcessOutputChunk[] {
  if (!isRecord(value)) return []
  const { seq, stream, text } = value
  if (typeof seq !== 'number' || !isStream(stream) || typeof text !== 'string') return []
  return [{ seq, stream, text }]
}

/** GET …/code/processes/{id}/output — chunks with `seq > cursor`. */
export async function getCodeProcessOutput(
  projectId: string,
  processId: string,
  machineId: string,
  cursor: number,
  client: ApiClient = api
): Promise<ProcessOutput> {
  const raw = await client.request<Record<string, unknown>>(
    `/projects/${seg(projectId)}/code/processes/${seg(processId)}/output?machine_id=${seg(machineId)}&cursor=${cursor}`
  )
  const output = isRecord(raw.output) ? raw.output : {}
  return {
    chunks: Array.isArray(output.chunks) ? output.chunks.flatMap(toProcessChunk) : [],
    cursor: typeof output.cursor === 'number' ? output.cursor : cursor,
    truncated: output.truncated === true
  }
}

/** POST …/code/processes/{id}/stop — the person's own Stop button. */
export function stopCodeProcess(
  projectId: string,
  processId: string,
  machineId: string,
  client: ApiClient = api
): Promise<unknown> {
  return client.request<unknown>(
    `/projects/${seg(projectId)}/code/processes/${seg(processId)}/stop?machine_id=${seg(machineId)}`,
    { method: 'POST' }
  )
}

// ---- input to an interactive process (§11.2 user input route) ------------

/** The route's bound on `text` (§11.1). */
export const MAX_PROCESS_INPUT_CHARS = 1024
// eslint-disable-next-line no-control-regex -- the point is to find them
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/

export interface ProcessInput {
  /** Printable text; a newline comes only from `enter`. */
  readonly text: string
  readonly enter: boolean
}

export interface ProcessInputResult {
  readonly ok: boolean
  readonly sentChars: number
  readonly reason: string | null
}

/** POST …/code/processes/{id}/input — the person's own answer to a waiting
 *  process, over their own bridge session. Refuses locally what the route
 *  would 422, so a bad keystroke never leaves the machine. */
export async function sendCodeProcessInput(
  projectId: string,
  processId: string,
  machineId: string,
  input: ProcessInput,
  client: ApiClient = api
): Promise<ProcessInputResult> {
  if (input.text.length > MAX_PROCESS_INPUT_CHARS) {
    throw new Error(`Input is limited to ${MAX_PROCESS_INPUT_CHARS} characters.`)
  }
  if (CONTROL_CHARS.test(input.text)) {
    throw new Error('Input can’t contain control characters.')
  }
  const raw = await client.request<Record<string, unknown>>(
    `/projects/${seg(projectId)}/code/processes/${seg(processId)}/input?machine_id=${seg(machineId)}`,
    { method: 'POST', body: { text: input.text, enter: input.enter } }
  )
  const sent = raw.sent_chars
  return {
    ok: raw.ok === true,
    sentChars: typeof sent === 'number' && Number.isSafeInteger(sent) && sent >= 0 ? sent : 0,
    reason: textOrNull(raw.reason)
  }
}
