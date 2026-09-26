// SOLUSDEV-311: a small JSON file in userData that outlives a crash —
// `pending` is the prior session's crash, handed once to the next renderer so
// it can emit the `client.error` event (main never holds the user token);
// `lastRelaunchAt` is the relaunch loop guard. Read defensively: anything that
// is not exactly the expected shape reads as empty. Never throws.
import { readFileSync, writeFileSync } from 'node:fs'
import {
  CRASH_ORIGINS,
  ERROR_NAMES,
  ERROR_SURFACES,
  isOneOf,
  type PendingCrash
} from './diagnostics.constants'

export const CRASH_MARKER_FILENAME = 'solus-crash.json'
/** A second main-process crash inside this window quits instead of relaunching. */
export const RELAUNCH_WINDOW_MS = 60_000

interface MarkerState {
  pending: PendingCrash | null
  lastRelaunchAt: number | null
}

export interface CrashMarkerIo {
  read: () => string | null
  write: (text: string) => void
}

export interface CrashMarker {
  record: (crash: PendingCrash) => void
  take: () => PendingCrash | null
  mayRelaunch: (nowMs: number) => boolean
  markRelaunch: (nowMs: number) => void
}

const EMPTY: MarkerState = { pending: null, lastRelaunchAt: null }

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

function asPending(v: unknown): PendingCrash | null {
  if (!isRecord(v)) return null
  const ok =
    isOneOf(CRASH_ORIGINS, v.origin) &&
    isOneOf(ERROR_SURFACES, v.surface) &&
    isOneOf(ERROR_NAMES, v.errorName) &&
    typeof v.fingerprint === 'string' &&
    /^[0-9a-f]{16}$/.test(v.fingerprint) &&
    typeof v.appVersion === 'string'
  return ok ? (v as unknown as PendingCrash) : null
}

function parse(text: string | null): MarkerState {
  if (!text) return EMPTY
  try {
    const raw: unknown = JSON.parse(text)
    if (!isRecord(raw)) return EMPTY
    const last = typeof raw.lastRelaunchAt === 'number' ? raw.lastRelaunchAt : null
    return { pending: asPending(raw.pending), lastRelaunchAt: last }
  } catch {
    return EMPTY
  }
}

export function createCrashMarker(io: CrashMarkerIo): CrashMarker {
  const load = (): MarkerState => {
    try {
      return parse(io.read())
    } catch {
      return EMPTY
    }
  }
  const save = (state: MarkerState): void => {
    try {
      io.write(JSON.stringify(state))
    } catch {
      // Best-effort: losing the marker only loses one event / one loop guard.
    }
  }
  return {
    record: (crash) => save({ ...load(), pending: crash }),
    take: () => {
      const state = load()
      if (state.pending) save({ ...state, pending: null })
      return state.pending
    },
    mayRelaunch: (nowMs) => {
      const last = load().lastRelaunchAt
      return last === null || nowMs - last > RELAUNCH_WINDOW_MS
    },
    markRelaunch: (nowMs) => save({ ...load(), lastRelaunchAt: nowMs })
  }
}

export function fileCrashMarkerIo(path: string): CrashMarkerIo {
  return {
    read: () => {
      try {
        return readFileSync(path, 'utf8')
      } catch {
        return null
      }
    },
    write: (text) => writeFileSync(path, text, { encoding: 'utf8', mode: 0o600 })
  }
}
