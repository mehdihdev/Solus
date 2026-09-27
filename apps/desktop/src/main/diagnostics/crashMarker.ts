// SOLUSDEV-311: a small JSON file in userData that outlives a crash —
// `pending` is the prior session's crash, handed once to the next renderer so
// it can emit the `client.error` event (main never holds the user token);
// `lastRelaunchAt` is the relaunch loop guard. Read defensively: anything that
// is not exactly the expected shape reads as empty. Never throws.
import { readFileSync, renameSync, writeFileSync } from 'node:fs'
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
  /** Persist the relaunch time; false when it could not be saved (the caller
   *  must then NOT relaunch — an unsaved guard cannot stop a loop). */
  markRelaunch: (nowMs: number) => boolean
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
  const save = (state: MarkerState): boolean => {
    try {
      io.write(JSON.stringify(state))
      return true
    } catch {
      // Losing the marker loses one event; markRelaunch reports it so the
      // loop guard fails closed.
      return false
    }
  }
  return {
    record: (crash) => void save({ ...load(), pending: crash }),
    take: () => {
      const state = load()
      if (state.pending) void save({ ...state, pending: null })
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
    // Temp + rename: a crash mid-write never leaves a half file behind.
    write: (text) => {
      const temp = `${path}.tmp`
      writeFileSync(temp, text, { encoding: 'utf8', mode: 0o600 })
      renameSync(temp, path)
    }
  }
}
