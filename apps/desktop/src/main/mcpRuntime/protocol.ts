// SOLUSDEV-329 — the `solus-companion runtime` JSON Lines protocol
// (docs/architecture/mcp-fork-runtime.md §6), desktop-main reader side.
//
// Every stdout line is untrusted: it is parsed against the documented shapes
// field by field, and anything oversize, not JSON, not `v: 1`, of an unknown
// `type` or with a malformed field is dropped and counted — never rendered,
// never thrown. Valid events come out with `v` removed and only the
// documented fields kept.

/** One line including its `\n` (§6). */
export const RUNTIME_LINE_MAX_BYTES = 4096
/** Whole-run stdout budget: far above the largest real run (6 forks × a few
 *  dozen progress lines), small enough that a runaway child cannot grow main. */
export const RUNTIME_TOTAL_MAX_BYTES = 4 * 1024 * 1024
const MESSAGE_MAX_CHARS = 300
const PATH_MAX_CHARS = 4096
const NEWLINE = 0x0a

export const RUNTIME_ERROR_CODES = [
  'python_not_found',
  'python_unsupported_version',
  'python_not_cpython',
  'python_store_alias',
  'python_probe_failed',
  'managed_not_installed',
  'venv_failed',
  'venv_copies_unhealthy',
  'pip_failed',
  'network_unreachable',
  'hash_mismatch',
  'wheel_unavailable',
  'managed_download_failed',
  'managed_hash_mismatch',
  'managed_too_large',
  'managed_extract_refused',
  'not_owner_only',
  'disk_full',
  'timeout',
  'cancelled',
  'internal'
] as const
export type RuntimeErrorCode = (typeof RUNTIME_ERROR_CODES)[number]

/** §5 `detail` codes. */
export const NEEDS_SETUP_DETAILS = [
  'needs_setup:no_env',
  'needs_setup:not_owner_only',
  'needs_setup:stamp_mismatch',
  'needs_setup:base_missing'
] as const
export type NeedsSetupDetail = (typeof NEEDS_SETUP_DETAILS)[number]

const IMPLEMENTATIONS = ['cpython', 'pypy', 'unknown'] as const
const SOURCES = ['path', 'py_launcher', 'registry', 'known_location', 'managed'] as const
const FORK_STATES = ['ready', 'needs_setup', 'unsupported_platform'] as const
const STEPS = ['download', 'verify', 'extract', 'venv', 'install', 'check', 'stamp'] as const
const FORK_OUTCOMES = ['ok', 'failed', 'skipped'] as const
const DONE_OUTCOMES = ['ok', 'partial', 'failed', 'cancelled'] as const

export const FORK_NAME_RE = /^[a-z][a-z0-9_-]{0,31}$/
const VERSION_RE = /^\d+\.\d+\.\d+$/

export interface Candidate {
  type: 'candidate'
  path: string
  version: string | null
  implementation: (typeof IMPLEMENTATIONS)[number]
  source: (typeof SOURCES)[number]
  supported: boolean
  reason: RuntimeErrorCode | null
}

export interface ForkStatus {
  type: 'status'
  fork: string
  state: (typeof FORK_STATES)[number]
  detail: NeedsSetupDetail | null
  base_version: string | null
  managed: boolean
}

export interface ProgressEvent {
  type: 'progress'
  fork: string | null
  step: (typeof STEPS)[number]
  done: number
  total: number | null
}

export interface ForkResult {
  type: 'fork_result'
  fork: string
  outcome: (typeof FORK_OUTCOMES)[number]
  error_code: RuntimeErrorCode | null
  message: string
}

export interface RuntimeErrorEvent {
  type: 'error'
  error_code: RuntimeErrorCode
  message: string
}

export interface DoneEvent {
  type: 'done'
  outcome: (typeof DONE_OUTCOMES)[number]
  ok: number
  failed: number
  skipped: number
}

export type RuntimeEvent =
  | Candidate
  | ForkStatus
  | ProgressEvent
  | ForkResult
  | RuntimeErrorEvent
  | DoneEvent

type Raw = Record<string, unknown>

const isRecord = (v: unknown): v is Raw => typeof v === 'object' && v !== null && !Array.isArray(v)
const oneOf =
  <T extends string>(values: readonly T[]) =>
  (v: unknown): v is T =>
    typeof v === 'string' && (values as readonly string[]).includes(v)
const nullable =
  <T>(guard: (v: unknown) => v is T) =>
  (v: unknown): v is T | null =>
    v === null || guard(v)
const isCount = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0
const isBool = (v: unknown): v is boolean => typeof v === 'boolean'
const isMessage = (v: unknown): v is string =>
  typeof v === 'string' && v.length <= MESSAGE_MAX_CHARS
const isVersion = (v: unknown): v is string => typeof v === 'string' && VERSION_RE.test(v)
export const isForkName = (v: unknown): v is string => typeof v === 'string' && FORK_NAME_RE.test(v)
export const isErrorCode = oneOf(RUNTIME_ERROR_CODES)

/** Absolute on POSIX (`/…`) or Windows (`C:\…`, `\\server\…`), bounded, NUL-free. */
export function isAbsolutePathString(v: unknown): v is string {
  if (typeof v !== 'string' || v.length === 0 || v.length > PATH_MAX_CHARS) return false
  if (v.includes('\0')) return false
  return v.startsWith('/') || /^[A-Za-z]:[\\/]/.test(v) || v.startsWith('\\\\')
}

type Shape = Readonly<Record<string, (v: unknown) => boolean>>

const SHAPES: Readonly<Record<RuntimeEvent['type'], Shape>> = {
  candidate: {
    path: isAbsolutePathString,
    version: nullable(isVersion),
    implementation: oneOf(IMPLEMENTATIONS),
    source: oneOf(SOURCES),
    supported: isBool,
    reason: nullable(isErrorCode)
  },
  status: {
    fork: isForkName,
    state: oneOf(FORK_STATES),
    detail: nullable(oneOf(NEEDS_SETUP_DETAILS)),
    base_version: nullable(isVersion),
    managed: isBool
  },
  progress: {
    fork: nullable(isForkName),
    step: oneOf(STEPS),
    done: isCount,
    total: nullable(isCount)
  },
  fork_result: {
    fork: isForkName,
    outcome: oneOf(FORK_OUTCOMES),
    error_code: nullable(isErrorCode),
    message: isMessage
  },
  error: { error_code: isErrorCode, message: isMessage },
  done: { outcome: oneOf(DONE_OUTCOMES), ok: isCount, failed: isCount, skipped: isCount }
}

const isEventType = (v: unknown): v is RuntimeEvent['type'] =>
  typeof v === 'string' && Object.hasOwn(SHAPES, v)

/** One stdout line → a validated event, or null (drop it). Never throws. */
export function parseRuntimeLine(line: string): RuntimeEvent | null {
  let raw: unknown
  try {
    raw = JSON.parse(line)
  } catch {
    return null
  }
  if (!isRecord(raw) || raw.v !== 1 || !isEventType(raw.type)) return null
  const shape = SHAPES[raw.type]
  const out: Raw = { type: raw.type }
  for (const [key, guard] of Object.entries(shape)) {
    if (!Object.hasOwn(raw, key) || !guard(raw[key])) return null
    out[key] = raw[key]
  }
  return out as unknown as RuntimeEvent
}

export interface RuntimeReaderStats {
  accepted: number
  dropped: number
  /** The total cap was hit; nothing after it was read. */
  overflow: boolean
}

export interface RuntimeLineReader {
  push(chunk: Buffer): void
  /** The stream ended: a final unterminated line is still a line. */
  end(): void
  stats(): RuntimeReaderStats
}

export interface RuntimeLineReaderOptions {
  onEvent: (event: RuntimeEvent) => void
  maxTotalBytes?: number
  /** Called once when the total cap is first exceeded (the caller kills the child). */
  onOverflow?: () => void
}

/** Byte-level line splitter (a chunk may end mid-UTF-8 sequence) with a
 *  per-line cap enforced while buffering: an over-long line is discarded up to
 *  its newline, never accumulated. */
export function createRuntimeLineReader(options: RuntimeLineReaderOptions): RuntimeLineReader {
  const maxTotal = options.maxTotalBytes ?? RUNTIME_TOTAL_MAX_BYTES
  const stats: RuntimeReaderStats = { accepted: 0, dropped: 0, overflow: false }
  let pending: Buffer[] = []
  let pendingBytes = 0
  let discarding = false
  let total = 0

  const emit = (bytes: Buffer): void => {
    if (bytes.length === 0) return
    const event = parseRuntimeLine(bytes.toString('utf8'))
    if (event === null) {
      stats.dropped++
      return
    }
    stats.accepted++
    options.onEvent(event)
  }

  const finishLine = (): void => {
    if (discarding) stats.dropped++
    else emit(Buffer.concat(pending, pendingBytes))
    pending = []
    pendingBytes = 0
    discarding = false
  }

  const append = (part: Buffer): void => {
    if (discarding) return
    // The cap counts the line's `\n`, so content may be at most max − 1 bytes.
    if (pendingBytes + part.length >= RUNTIME_LINE_MAX_BYTES) {
      pending = []
      pendingBytes = 0
      discarding = true
      return
    }
    pending.push(part)
    pendingBytes += part.length
  }

  const overflowed = (chunk: Buffer): boolean => {
    if (stats.overflow) return true
    total += chunk.length
    if (total <= maxTotal) return false
    stats.overflow = true
    pending = []
    pendingBytes = 0
    options.onOverflow?.()
    return true
  }

  return {
    push(chunk) {
      if (overflowed(chunk)) return
      let start = 0
      for (let i = chunk.indexOf(NEWLINE); i !== -1; i = chunk.indexOf(NEWLINE, start)) {
        append(chunk.subarray(start, i))
        finishLine()
        start = i + 1
      }
      if (start < chunk.length) append(chunk.subarray(start))
    },
    end() {
      if (stats.overflow) return
      if (pendingBytes > 0 || discarding) finishLine()
    },
    stats: () => ({ ...stats })
  }
}
