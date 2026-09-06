// SOLUSDEV-244 / HOME H3: ~/.solus/preferences.json — the user's engineering
// preferences (ADR-034 amendment 2026-09-06; docs/contracts/local-state.md).
// The one Layer-1 file the USER authors: how they engineer. The server never
// reads ~/.solus — the renderer loads this through the sender-gated IPC below
// and attaches it to each SOL turn, where the API re-validates it.
//
// Same posture as solChatCache: deps-injected so tests need no filesystem, the
// shared strict parser runs in THIS process (a fork or a hand edit can put
// anything in the file), sizes are gated in BYTES before materializing,
// writes are atomic temp+rename with 0600 under the re-tightened 0700 home,
// a NEWER schema_version's file is read-only to this app, and a corrupt file
// degrades to the empty document rather than crashing a reader.
import {
  ENGINEERING_PREFERENCES_SCHEMA_VERSION,
  PREFERENCES_FILENAME,
  PREFERENCES_MAX_BYTES,
  SOLUS_HOME_DIRNAME,
  SOLUS_HOME_MODE,
  emptyEngineeringPreferences,
  parseEngineeringPreferences,
  type EngineeringPreferences
} from '@solus/shared-types'
import { randomBytes } from 'node:crypto'
import { chmodSync, lstatSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export interface PreferencesStoreDeps {
  homedir: () => string
  readFile: (path: string) => string
  writeFile: (path: string, content: string, mode: number) => void
  /** Move `from` over `to`, replacing it — atomic on POSIX. */
  replaceFile: (from: string, to: string) => void
  mkdir: (path: string, mode: number) => void
  chmod: (path: string, mode: number) => void
  /** Size in bytes when `path` is a REGULAR file (lstat — a symlink planted at
   *  the path is refused, never followed); null otherwise. */
  fileSize: (path: string) => number | null
  now: () => Date
}

/** The user's own conventions — owner read/write only. */
const PREFERENCES_FILE_MODE = 0o600

export interface PreferencesRead {
  preferences: EngineeringPreferences
  /** True when the file was written by a NEWER app: shown, never overwritten. */
  readOnly: boolean
}

function homePath(deps: PreferencesStoreDeps): string {
  return join(deps.homedir(), SOLUS_HOME_DIRNAME)
}

function filePath(deps: PreferencesStoreDeps): string {
  return join(homePath(deps), PREFERENCES_FILENAME)
}

/** Parse whatever is on disk. Missing/corrupt/oversized ⇒ empty; newer ⇒ empty + readOnly. */
export function readPreferences(deps: PreferencesStoreDeps): PreferencesRead {
  const empty = { preferences: emptyEngineeringPreferences(), readOnly: false }
  const path = filePath(deps)
  try {
    const size = deps.fileSize(path)
    if (size === null || size > PREFERENCES_MAX_BYTES) return empty
    const parsed = parseEngineeringPreferences(JSON.parse(deps.readFile(path)))
    if (parsed.ok) return { preferences: parsed.preferences, readOnly: false }
    return parsed.reason === 'newer' ? { ...empty, readOnly: true } : empty
  } catch {
    return empty
  }
}

/** Validate, stamp, and atomically write the document. False on any refusal. */
export function writePreferences(document: unknown, deps: PreferencesStoreDeps): boolean {
  // The renderer's copy is re-parsed here: the caps and the strict shape are
  // enforced by the process that owns the file, not trusted from IPC.
  const parsed = parseEngineeringPreferences(document)
  if (!parsed.ok) return false
  // A file written by a NEWER app version is read-only to this one.
  if (readPreferences(deps).readOnly) return false
  const stamped: EngineeringPreferences = {
    ...parsed.preferences,
    schema_version: ENGINEERING_PREFERENCES_SCHEMA_VERSION,
    updatedAt: deps.now().toISOString()
  }
  const content = JSON.stringify(stamped, null, 2) + '\n'
  if (Buffer.byteLength(content, 'utf8') > PREFERENCES_MAX_BYTES) return false
  try {
    const home = homePath(deps)
    deps.mkdir(home, SOLUS_HOME_MODE)
    // Re-tighten the home even when it pre-existed under a looser umask.
    deps.chmod(home, SOLUS_HOME_MODE)
    // Atomic: temp in the SAME directory, then rename over the target — a
    // crash never tears the file, and a symlink at the target is REPLACED,
    // never written through (ADR-034 write rule).
    const temp = join(home, `.${PREFERENCES_FILENAME}.${randomBytes(4).toString('hex')}.tmp`)
    deps.writeFile(temp, content, PREFERENCES_FILE_MODE)
    const target = filePath(deps)
    deps.replaceFile(temp, target)
    deps.chmod(target, PREFERENCES_FILE_MODE)
    return true
  } catch {
    return false
  }
}

/** The IPC seam: every channel's full decision — sender gate, argument
 *  validation, caps — lives HERE where it is testable; index.ts only wires
 *  ipcMain to these with the real sender check and deps. */
export const preferencesIpc = {
  read(senderOk: boolean, deps: PreferencesStoreDeps): PreferencesRead | null {
    return senderOk ? readPreferences(deps) : null
  },
  write(senderOk: boolean, document: unknown, deps: PreferencesStoreDeps): { ok: boolean } {
    return { ok: senderOk ? writePreferences(document, deps) : false }
  }
}

export const realPreferencesStoreDeps: PreferencesStoreDeps = {
  homedir,
  readFile: (path) => readFileSync(path, 'utf8'),
  // 'wx': create exclusively — never write through a symlink planted at the
  // temp path, never inherit a pre-existing file's mode (SEC review L6).
  writeFile: (path, content, mode) =>
    writeFileSync(path, content, { encoding: 'utf8', mode, flag: 'wx' }),
  replaceFile: (from, to) => renameSync(from, to),
  mkdir: (path, mode) => void mkdirSync(path, { recursive: true, mode }),
  chmod: (path, mode) => chmodSync(path, mode),
  fileSize: (path) => {
    try {
      const stat = lstatSync(path)
      return stat.isFile() ? stat.size : null
    } catch {
      return null
    }
  },
  now: () => new Date()
}
