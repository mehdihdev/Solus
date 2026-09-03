// SOLUSDEV-235 / EXT-05 — the ONE injected filesystem surface every extension
// module (index, installer, developer mode, protocol) reads and writes through.
// Same idiom as localState.ts / solChatCache.ts: production binds node:fs, tests
// bind an in-memory tree, and no decision in this directory needs a real
// home directory to be proven.
import { randomBytes } from 'node:crypto'
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { homedir } from 'node:os'

export interface ExtensionFs {
  homedir: () => string
  /** Bytes of a file; throws when missing/unreadable. */
  readFile: (path: string) => Uint8Array
  writeFile: (path: string, data: Uint8Array | string, mode: number) => void
  /** Move `from` to `to` (a file replaces a file — atomic on POSIX; a directory
   *  must land on a free name). */
  rename: (from: string, to: string) => void
  /** Create the directory (parents included) with the given mode. */
  mkdir: (path: string, mode: number) => void
  chmod: (path: string, mode: number) => void
  /** Recursive, force delete of a file or directory; absent is fine. */
  remove: (path: string) => void
  /** Canonical absolute path (symlinks and dot-segments resolved), or null
   *  when it does not exist. Every containment check runs on THIS value. */
  realpath: (path: string) => string | null
  isDirectory: (path: string) => boolean
  /** Size in bytes when `path` is a REGULAR file (lstat — a symlink planted at
   *  the path is refused, never followed); null otherwise. */
  fileSize: (path: string) => number | null
  tempSuffix: () => string
  now: () => Date
  /** Non-fatal diagnostics (a corrupt index is worth a line, not a crash). */
  warn: (message: string) => void
}

/** Cache files and directories are owner-only, like everything in ~/.solus. */
export const EXTENSION_FILE_MODE = 0o600
export const EXTENSION_DIR_MODE = 0o700

export const realExtensionFs: ExtensionFs = {
  homedir,
  readFile: (path) => new Uint8Array(readFileSync(path)),
  writeFile: (path, data, mode) => writeFileSync(path, data, { mode }),
  rename: (from, to) => renameSync(from, to),
  mkdir: (path, mode) => void mkdirSync(path, { recursive: true, mode }),
  chmod: (path, mode) => {
    if (process.platform !== 'win32') chmodSync(path, mode)
  },
  remove: (path) => rmSync(path, { recursive: true, force: true }),
  realpath: (path) => {
    try {
      return realpathSync.native(path)
    } catch {
      return null
    }
  },
  isDirectory: (path) => {
    try {
      return statSync(path).isDirectory()
    } catch {
      return false
    }
  },
  fileSize: (path) => {
    try {
      const stat = lstatSync(path)
      return stat.isFile() ? stat.size : null
    } catch {
      return null
    }
  },
  tempSuffix: () => randomBytes(6).toString('hex'),
  now: () => new Date(),
  warn: (message) => console.warn(message)
}
