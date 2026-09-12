// SOLUSDEV-252 S3: the `sol` key of ~/.solus/config.json (docs/architecture/
// sol-window.md §7, ADR-034 layer 1, main-owned). Reuses the localState
// atomic-write deps; same posture as preferencesStore: a corrupt file degrades
// to defaults with one warning, a NEWER schema_version's file is read-only to
// this app, and nothing here ever throws to a caller. Other top-level keys in
// config.json are preserved verbatim.
import { SOLUS_HOME_DIRNAME, SOLUS_HOME_MODE } from '@solus/shared-types'
import { join } from 'node:path'
import type { LocalStateDeps } from './localState'

export const SOL_CONFIG_FILENAME = 'config.json'
export const SOL_CONFIG_SCHEMA_VERSION = 1
const CONFIG_FILE_MODE = 0o600
const MAX_CONFIG_BYTES = 64 * 1024

export type SolActionMode = 'guide' | 'do'

export interface SolWindowGeometry {
  x: number
  y: number
  width: number
  height: number
  displayId: number
}

export interface SolSettingsState {
  actionMode: SolActionMode
  screenIntelligence: boolean
  /** The native key hook + cursor sampler (double-tap Ctrl, Ctrl-hold circle).
   *  Off stops both; the global chords stay. The consent surface for a global
   *  keyboard hook (security review L2). */
  hotkeys: boolean
  alwaysOnTop: boolean
  window: SolWindowGeometry | null
}

export const DEFAULT_SOL_SETTINGS: SolSettingsState = {
  actionMode: 'guide',
  screenIntelligence: false,
  hotkeys: true,
  alwaysOnTop: false,
  window: null
}

export type SolSettingsDeps = Pick<
  LocalStateDeps,
  | 'homedir'
  | 'readFile'
  | 'writeFile'
  | 'replaceFile'
  | 'mkdir'
  | 'chmod'
  | 'remove'
  | 'tempSuffix'
  | 'warn'
>

export interface SolSettings {
  get(): SolSettingsState
  setMode(mode: SolActionMode): void
  toggleMode(): SolActionMode
  setScreenIntelligence(on: boolean): void
  setHotkeys(on: boolean): void
  setAlwaysOnTop(on: boolean): void
  setWindowGeometry(geometry: SolWindowGeometry | null): void
  /** Hear every change (the new state); returns unsubscribe. */
  onChange(cb: (state: SolSettingsState) => void): () => void
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

function parseGeometry(v: unknown): SolWindowGeometry | null {
  if (!isRecord(v)) return null
  const nums = ['x', 'y', 'width', 'height', 'displayId'].map((k) => v[k])
  if (!nums.every((n) => typeof n === 'number' && Number.isFinite(n))) return null
  const [x, y, width, height, displayId] = nums as number[]
  return { x, y, width, height, displayId }
}

/** Pick only the known fields; anything malformed falls back to its default. */
export function parseSolSettings(v: unknown): SolSettingsState {
  const r = isRecord(v) ? v : {}
  return {
    actionMode: r.actionMode === 'do' ? 'do' : 'guide',
    screenIntelligence: r.screenIntelligence === true,
    hotkeys: r.hotkeys !== false,
    alwaysOnTop: r.alwaysOnTop === true,
    window: parseGeometry(r.window)
  }
}

interface ConfigRead {
  doc: Record<string, unknown>
  sol: SolSettingsState
  writable: boolean
}

function readConfig(path: string, deps: SolSettingsDeps): ConfigRead {
  const fallback: ConfigRead = { doc: {}, sol: DEFAULT_SOL_SETTINGS, writable: true }
  let raw: string
  try {
    raw = deps.readFile(path)
  } catch {
    return fallback
  }
  let value: unknown
  try {
    if (raw.length > MAX_CONFIG_BYTES) throw new Error('size cap')
    value = JSON.parse(raw)
    if (!isRecord(value)) throw new Error('not an object')
  } catch {
    deps.warn('[sol-settings] config.json is not valid; using defaults')
    return fallback
  }
  const version = value.schema_version
  if (typeof version === 'number' && version > SOL_CONFIG_SCHEMA_VERSION) {
    deps.warn('[sol-settings] config.json has a newer schema_version; leaving it untouched')
    return { doc: value, sol: DEFAULT_SOL_SETTINGS, writable: false }
  }
  return { doc: value, sol: parseSolSettings(value.sol), writable: true }
}

export function createSolSettings(deps: SolSettingsDeps): SolSettings {
  const home = join(deps.homedir(), SOLUS_HOME_DIRNAME)
  const path = join(home, SOL_CONFIG_FILENAME)
  const read = readConfig(path, deps)
  let state = read.sol
  const listeners = new Set<(state: SolSettingsState) => void>()

  const write = (): void => {
    if (!read.writable) return
    try {
      deps.mkdir(home, SOLUS_HOME_MODE)
      deps.chmod(home, SOLUS_HOME_MODE)
      const doc = { ...read.doc, schema_version: SOL_CONFIG_SCHEMA_VERSION, sol: state }
      const temp = `${path}.${deps.tempSuffix()}.tmp`
      deps.writeFile(temp, `${JSON.stringify(doc, null, 2)}\n`, CONFIG_FILE_MODE)
      try {
        deps.replaceFile(temp, path)
      } catch (error) {
        deps.remove(temp)
        throw error
      }
    } catch (error) {
      deps.warn(`[sol-settings] could not write config.json: ${String(error)}`)
    }
  }

  const update = (patch: Partial<SolSettingsState>): void => {
    state = { ...state, ...patch }
    write()
    for (const cb of [...listeners]) cb(state)
  }

  return {
    get: () => state,
    setMode: (actionMode) => update({ actionMode }),
    toggleMode: () => {
      const actionMode: SolActionMode = state.actionMode === 'guide' ? 'do' : 'guide'
      update({ actionMode })
      return actionMode
    },
    setScreenIntelligence: (screenIntelligence) => update({ screenIntelligence }),
    setHotkeys: (hotkeys) => update({ hotkeys }),
    setAlwaysOnTop: (alwaysOnTop) => update({ alwaysOnTop }),
    setWindowGeometry: (window) => update({ window }),
    onChange: (cb) => {
      listeners.add(cb)
      return () => void listeners.delete(cb)
    }
  }
}
