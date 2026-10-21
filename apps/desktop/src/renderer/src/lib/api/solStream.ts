// SOL's Server-Sent Events stream (SOLUSDEV-96 / ONS-UI-01).
//
// The backend streams a turn as SSE frames: `event: <type>\ndata: <json>\n\n`.
// `fetch` is used directly HERE and only here — the typed client wraps JSON
// request/response, which a streaming body is not. Components never see fetch
// (CLAUDE.md §8); they consume `streamSolTurn`.
//
// The frame parser is a pure function so the interesting behaviour — partial
// chunks, multi-frame chunks, malformed JSON — is testable without a network.
import { joinUrl } from './client'

/** Event types SOL streams. Unknown types are ignored, not fatal: the backend
 *  may add one before this app knows about it. */
export type SolEventType =
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'tool_confirmation'
  | 'artifact'
  | 'message'
  | 'error'
  | 'done'

export interface SolEvent {
  readonly type: SolEventType | string
  readonly data: Record<string, unknown>
}

/** One row of the diff a user is approving. Generic across tool kinds — a CAD
 *  edit, a firmware flash and a robot command all render the same shape. */
export interface ConfirmationRow {
  readonly label: string
  readonly before: string | null
  readonly after: string | null
}

export interface PendingConfirmation {
  readonly confirmationId: string
  readonly tool: string
  readonly summary: string
  readonly preview: readonly ConfirmationRow[]
}

function asRows(value: unknown): ConfirmationRow[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return []
    const row = entry as Record<string, unknown>
    if (typeof row.label !== 'string') return []
    return [
      {
        label: row.label,
        before: typeof row.before === 'string' ? row.before : null,
        after: typeof row.after === 'string' ? row.after : null
      }
    ]
  })
}

/** Read a `tool_confirmation` event's payload, or null when it is unusable.
 *  Defensive because the payload crosses a process boundary. */
export function toPendingConfirmation(event: SolEvent): PendingConfirmation | null {
  const { confirmation_id: id, tool, summary, preview } = event.data
  if (typeof id !== 'string' || typeof tool !== 'string') return null
  return {
    confirmationId: id,
    tool,
    summary: typeof summary === 'string' ? summary : tool,
    preview: asRows(preview)
  }
}

/** A tool's large/binary output, referenced never inlined (agent-tool.md §4;
 *  SOLUSDEV-252 S5). `uri` is the API content route — bytes need the bearer. */
export interface SolArtifact {
  readonly artifactId: string
  readonly uri: string
  readonly mediaType: string
  readonly title: string
  readonly sourceTool: string | null
  readonly summary: string | null
}

const optionalText = (value: unknown): string | null => (typeof value === 'string' ? value : null)

/** Read an `artifact` event's payload, or null when it cannot name its bytes. */
export function toSolArtifact(event: SolEvent): SolArtifact | null {
  const { artifact_id: id, uri, media_type: mediaType, title, source_tool, summary } = event.data
  if (typeof id !== 'string' || typeof uri !== 'string' || typeof mediaType !== 'string') {
    return null
  }
  const sourceTool = optionalText(source_tool)
  return {
    artifactId: id,
    uri,
    mediaType,
    title: optionalText(title) ?? sourceTool ?? 'Artifact',
    sourceTool,
    summary: optionalText(summary)
  }
}

/** A Build-mode `code.exec` that ran without a card (code-command-execution.md
 *  §10.1), as the transcript shows it. Untrusted machine text — plain text only. */
export interface AutoRun {
  readonly callId: string
  /** The program's basename. */
  readonly program: string
  /** `exited N`, `timed out`, … as the cloud words it. */
  readonly status: string
  /** stdout then stderr tails. */
  readonly output: string
}

/** Per-tail ceiling: above the code server's 16 KiB tail window. */
export const AUTO_RUN_TAIL_CHARS = 32_768
const AUTO_RUN_PROGRAM_CHARS = 256
const AUTO_RUN_STATUS_CHARS = 200

/** Join stdout and stderr tails as one plain-text block (stdout first). */
export function joinTails(stdout: string, stderr: string): string {
  if (!stdout || !stderr) return stdout + stderr
  return stdout.endsWith('\n') ? stdout + stderr : `${stdout}\n${stderr}`
}

/** An optional tail: absent reads as empty, anything but a string is junk. */
function tailOf(value: unknown): string | null {
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value.slice(-AUTO_RUN_TAIL_CHARS) : null
}

function basename(program: string): string {
  return program.split(/[\\/]/).filter(Boolean).pop() ?? ''
}

/** Read an auto-run row from a `tool_result` payload `{call_id, tool, auto:
 *  true, program, status, stdout_tail, stderr_tail}`, or null — any unknown or
 *  missing field means no row. */
export function toAutoRun(data: Record<string, unknown>): AutoRun | null {
  const { call_id: callId, tool, auto, program, status } = data
  if (auto !== true || tool !== 'code.exec' || typeof callId !== 'string') return null
  if (typeof program !== 'string' || typeof status !== 'string' || !status) return null
  const name = basename(program).slice(0, AUTO_RUN_PROGRAM_CHARS)
  const stdout = tailOf(data.stdout_tail)
  const stderr = tailOf(data.stderr_tail)
  if (!name || stdout === null || stderr === null) return null
  return {
    callId,
    program: name,
    status: status.slice(0, AUTO_RUN_STATUS_CHARS),
    output: joinTails(stdout, stderr)
  }
}

/**
 * Split an SSE buffer into complete frames plus the unconsumed remainder.
 *
 * Network chunks do not align with frame boundaries: one chunk may carry three
 * frames, or half of one. The remainder is carried into the next call, which is
 * why this returns it rather than swallowing it.
 */
export function parseSseBuffer(buffer: string): { events: SolEvent[]; rest: string } {
  const events: SolEvent[] = []
  const parts = buffer.split('\n\n')
  // The final part is incomplete unless the buffer ended on a boundary.
  const rest = parts.pop() ?? ''
  for (const frame of parts) {
    const event = parseSseFrame(frame)
    if (event) events.push(event)
  }
  return { events, rest }
}

/** One `event:`/`data:` frame → an event, or null when it is malformed.
 *  A bad frame is skipped rather than throwing: one unparseable event must not
 *  kill a turn that is otherwise streaming fine. */
export function parseSseFrame(frame: string): SolEvent | null {
  let type = ''
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!type) return null
  try {
    const parsed: unknown = JSON.parse(dataLines.join('\n') || '{}')
    if (!parsed || typeof parsed !== 'object') return null
    return { type, data: parsed as Record<string, unknown> }
  } catch {
    return null
  }
}

export interface StreamSolTurnOptions {
  readonly projectId: string
  readonly conversationId: string
  readonly content: string
  readonly baseUrl: string
  readonly getToken: () => Promise<string | null> | string | null
  readonly signal?: AbortSignal
  readonly fetchImpl?: typeof fetch
}

/** Post a message and yield SOL's events as they arrive. */
export async function* streamSolTurn(options: StreamSolTurnOptions): AsyncGenerator<SolEvent> {
  const doFetch = options.fetchImpl ?? fetch
  const token = await options.getToken()
  const response = await doFetch(
    joinUrl(
      options.baseUrl,
      `/projects/${options.projectId}/sol/conversations/${options.conversationId}/messages`
    ),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify({ content: options.content }),
      signal: options.signal
    }
  )
  if (!response.ok || !response.body) {
    yield {
      type: 'error',
      data: { code: 'stream_failed', message: `SOL returned ${response.status}` }
    }
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const { events, rest } = parseSseBuffer(buffer)
      buffer = rest
      for (const event of events) yield event
    }
  } finally {
    reader.releaseLock()
  }
}
