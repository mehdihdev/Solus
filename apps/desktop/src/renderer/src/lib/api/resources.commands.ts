// SOLUSDEV-317 — typed clients for SOL command execution
// (docs/api/code-command-execution.md §6 and code-environment.md "Incremental
// command output"). Hand-typed until schema.ts is regenerated. Every answer
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
}

export interface CodeProcessList {
  readonly bridge: { readonly connected: boolean }
  readonly processes: readonly CodeProcess[]
}

const textOrNull = (value: unknown): string | null => (typeof value === 'string' ? value : null)
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' ? value : null)

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
      sandbox: textOrNull(value.sandbox)
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
