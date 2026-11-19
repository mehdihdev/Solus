// SOLUSDEV-329 — the `mcp_runtime` key of ~/.solus/config.json
// (docs/architecture/mcp-fork-runtime.md §8, docs/contracts/local-state.md):
// this machine's base interpreter for the MCP fork environments.
//
// Desktop main is the only writer. Same posture as solSettings: never throws
// to a caller, 64 KiB cap, 0600 atomic writes, `sol` and every unknown key
// preserved verbatim, a newer file-level OR `mcp_runtime` schema_version is
// read-only. Unlike solSettings the file is re-read at every read and write,
// so a `sol` change made since start-up is never written back stale.
import { SOLUS_HOME_DIRNAME, SOLUS_HOME_MODE } from '@solus/shared-types'
import { join } from 'node:path'
import { writeFileAtomically, type LocalStateDeps } from '../localState'
import { SOL_CONFIG_FILENAME, SOL_CONFIG_SCHEMA_VERSION } from '../solSettings'
import { isAbsolutePathString } from './protocol'
import type { ChoiceView } from './channels'

export const MCP_RUNTIME_SCHEMA_VERSION = 1
const CONFIG_FILE_MODE = 0o600
const MAX_CONFIG_BYTES = 64 * 1024

/** A saved choice: `path` is set exactly when the mode is `path`. */
export type RuntimeChoice =
  | { mode: 'auto' | 'managed'; path: null }
  | { mode: 'path'; path: string }

/** A renderer request: `{ mode: 'path' }` with no path asks main's picker. */
export type ChoiceRequest = RuntimeChoice | { mode: 'path'; path: null }

export type RuntimeSettingsDeps = Pick<
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

export interface RuntimeSettings {
  read(): ChoiceView
  /** False when the file is read-only to this build or the write failed. */
  write(choice: RuntimeChoice): boolean
}

const AUTO: RuntimeChoice = { mode: 'auto', path: null }

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const hasOnlyKeys = (r: Record<string, unknown>, keys: readonly string[]): boolean =>
  Object.keys(r).every((k) => keys.includes(k))

/** Untrusted `{ mode, path? }` → a choice request, or null. */
export function parseChoiceInput(value: unknown): ChoiceRequest | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['mode', 'path'])) return null
  const { mode, path } = value
  if (mode === 'auto' || mode === 'managed') return path === undefined ? { mode, path: null } : null
  if (mode !== 'path') return null
  if (path === undefined || path === null) return { mode: 'path', path: null }
  return isAbsolutePathString(path) ? { mode: 'path', path } : null
}

/** The stored `python` object → a saved choice (picker requests are not stored). */
function parsePython(value: unknown): RuntimeChoice | null {
  const choice = parseChoiceInput(value)
  return choice === null || (choice.mode === 'path' && choice.path === null)
    ? null
    : (choice as RuntimeChoice)
}

interface ConfigRead {
  doc: Record<string, unknown>
  choice: RuntimeChoice
  writable: boolean
}

function parseRuntime(value: unknown, deps: RuntimeSettingsDeps): Omit<ConfigRead, 'doc'> {
  if (value === undefined) return { choice: AUTO, writable: true }
  if (isRecord(value)) {
    const version = value.schema_version
    if (typeof version === 'number' && version > MCP_RUNTIME_SCHEMA_VERSION) {
      deps.warn('[mcp-runtime] mcp_runtime has a newer schema_version; leaving it untouched')
      return { choice: AUTO, writable: false }
    }
    const python =
      version === MCP_RUNTIME_SCHEMA_VERSION && hasOnlyKeys(value, ['schema_version', 'python'])
        ? parsePython(value.python)
        : null
    if (python !== null) return { choice: python, writable: true }
  }
  deps.warn('[mcp-runtime] mcp_runtime is not valid; using auto')
  return { choice: AUTO, writable: true }
}

function readConfig(path: string, deps: RuntimeSettingsDeps): ConfigRead {
  const fresh: ConfigRead = { doc: {}, choice: AUTO, writable: true }
  let raw: string
  try {
    raw = deps.readFile(path)
  } catch {
    return fresh
  }
  let value: unknown
  try {
    if (raw.length > MAX_CONFIG_BYTES) throw new Error('size cap')
    value = JSON.parse(raw)
  } catch {
    value = null
  }
  if (!isRecord(value)) {
    deps.warn('[mcp-runtime] config.json is not valid; using defaults')
    return fresh
  }
  const version = value.schema_version
  if (typeof version === 'number' && version > SOL_CONFIG_SCHEMA_VERSION) {
    deps.warn('[mcp-runtime] config.json has a newer schema_version; leaving it untouched')
    return { doc: value, choice: AUTO, writable: false }
  }
  return { doc: value, ...parseRuntime(value.mcp_runtime, deps) }
}

const storedPython = (choice: RuntimeChoice): Record<string, string> =>
  choice.mode === 'path' ? { mode: 'path', path: choice.path } : { mode: choice.mode }

export function createRuntimeSettings(deps: RuntimeSettingsDeps): RuntimeSettings {
  const home = join(deps.homedir(), SOLUS_HOME_DIRNAME)
  const path = join(home, SOL_CONFIG_FILENAME)
  return {
    read() {
      const { choice, writable } = readConfig(path, deps)
      return { mode: choice.mode, path: choice.path, writable }
    },
    write(choice) {
      const current = readConfig(path, deps)
      if (!current.writable) return false
      const doc = {
        ...current.doc,
        schema_version: SOL_CONFIG_SCHEMA_VERSION,
        mcp_runtime: { schema_version: MCP_RUNTIME_SCHEMA_VERSION, python: storedPython(choice) }
      }
      try {
        deps.mkdir(home, SOLUS_HOME_MODE)
        deps.chmod(home, SOLUS_HOME_MODE)
        writeFileAtomically(path, `${JSON.stringify(doc, null, 2)}\n`, CONFIG_FILE_MODE, deps)
        return true
      } catch (error) {
        deps.warn(`[mcp-runtime] could not write config.json: ${String(error)}`)
        return false
      }
    }
  }
}
