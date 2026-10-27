// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the helper's
// pinned path, and the desktop's own `solus-input trust [--prompt]` call for
// the Settings permission rows. Posts nothing, captures nothing (§2), but it is
// still a subprocess: argument list, no shell, a PATH-only environment, one
// deadline, a stdout cap — and its output is untrusted until parsed.
import { execFile } from 'node:child_process'
import { accessSync, constants, lstatSync } from 'node:fs'
import { dirname, isAbsolute, join, normalize, sep } from 'node:path'
import { findAncestorPath } from '../companionEnv'
import type { DriveTrust } from './driveStatus'

export const DRIVE_TRUST_TIMEOUT_MS = 5_000
export const DRIVE_TRUST_MAX_STDOUT = 64 * 1024
const TRUST_ENV = { PATH: '/usr/bin:/bin' } as const

/** Packaged: the launcher, which disclaims responsibility before exec'ing the helper. */
const PACKAGED_HELPER = ['SolusInput.app', 'Contents', 'MacOS', 'solus-input-launch'] as const
/** Dev: the unsigned debug helper (grants belong to whatever launched the app). */
const DEV_HELPER = [
  'apps',
  'desktop',
  'native',
  'solus-input',
  '.build',
  'debug',
  'solus-input'
] as const

export interface DriveHelperRuntime {
  isPackaged: boolean
  resourcesPath: string
  /** `app.getAppPath()` — `<repo>/apps/desktop` or a build output under it. */
  appPath: string
  exists: (path: string) => boolean
  /** Canonical path or null. The dev `.build/debug` is a symlink into
   *  `.build/out/Products/Debug`, and the companion refuses any symlink on the
   *  helper path (§3), so the dev path is resolved first. */
  realpath: (path: string) => string | null
}

/** The helper path the companion gets as SOLUS_DRIVE_HELPER and `trust` runs,
 *  or null when a dev run has no (resolvable) debug build. Packaged, the path
 *  is returned as-is — never realpath-ed, so a planted symlink still trips the
 *  companion's check; the caller's executable check decides `no_helper`. */
export function resolveDriveHelper(rt: DriveHelperRuntime): string | null {
  if (rt.isPackaged) return join(rt.resourcesPath, ...PACKAGED_HELPER)
  const dev = findAncestorPath(rt.appPath, DEV_HELPER, rt.exists)
  return dev === null ? null : rt.realpath(dev)
}

export interface DriveTrustResult {
  trust: DriveTrust
  unsignedDev: boolean
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/** Exactly one JSON object `{ok:true, trust:{accessibility,screenRecording}, unsignedDev?}`;
 *  null for anything else. */
export function parseTrustOutput(stdout: string): DriveTrustResult | null {
  const lines = stdout.split('\n').filter((line) => line.trim().length > 0)
  if (lines.length !== 1) return null
  let value: unknown
  try {
    value = JSON.parse(lines[0])
  } catch {
    return null
  }
  if (!isRecord(value) || value.ok !== true || !isRecord(value.trust)) return null
  const { accessibility, screenRecording } = value.trust
  if (typeof accessibility !== 'boolean' || typeof screenRecording !== 'boolean') return null
  const unsignedDev = value.unsignedDev ?? false
  if (typeof unsignedDev !== 'boolean') return null
  return { trust: { accessibility, screenRecording }, unsignedDev }
}

export interface TrustExecOptions {
  env: Record<string, string>
  timeout: number
  maxBuffer: number
  killSignal: 'SIGKILL'
  shell: false
  windowsHide: true
}

/** The slice of `child_process.execFile` the runner needs (injected for tests). */
export type TrustExec = (
  file: string,
  args: string[],
  options: TrustExecOptions,
  callback: (error: Error | null, stdout: string) => void
) => void

/** Run `trust` (or `trust --prompt`); null on any failure — the row then shows
 *  no grants rather than a guess. */
export function runDriveTrust(
  helper: string,
  prompt: boolean,
  exec: TrustExec
): Promise<DriveTrustResult | null> {
  const args = prompt ? ['trust', '--prompt'] : ['trust']
  const options: TrustExecOptions = {
    env: { ...TRUST_ENV },
    timeout: DRIVE_TRUST_TIMEOUT_MS,
    maxBuffer: DRIVE_TRUST_MAX_STDOUT,
    killSignal: 'SIGKILL',
    shell: false,
    windowsHide: true
  }
  return new Promise((resolve) => {
    try {
      exec(helper, args, options, (error, stdout) =>
        resolve(error ? null : parseTrustOutput(String(stdout)))
      )
    } catch {
      resolve(null)
    }
  })
}

export interface HelperStat {
  isFile: boolean
  isDirectory: boolean
  isSymbolicLink: boolean
  mode: number
  uid: number
}

/** lstat (never follows a link) + an X_OK check; injected for tests. */
export interface HelperFs {
  lstat(path: string): HelperStat | null
  canExecute(path: string): boolean
}

const S_IWGRP = 0o020
const S_IWOTH = 0o002
const S_ISVTX = 0o1000

/** A directory whose entries someone other than its owner (or root) could replace. */
function replaceableDir(info: HelperStat): boolean {
  if (info.mode & S_ISVTX) return false // sticky: others cannot replace our entry
  if (info.mode & S_IWOTH) return true
  return (info.mode & S_IWGRP) !== 0 && info.uid !== 0 // root:admin 0775 (/Applications) is fine
}

/** The path's ancestors, nearest first, ending at `/`. */
function ancestors(path: string): string[] {
  const out: string[] = []
  for (let dir = dirname(path); ; dir = dirname(dir)) {
    out.push(dir)
    if (dirname(dir) === dir) return out
  }
}

/**
 * Whether the companion would accept `path` as SOLUS_DRIVE_HELPER (mirrors
 * packages/companion drive/helper.py `resolve_helper`), so Settings never says
 * "available" for a helper the companion then refuses: absolute and normal; no
 * symlink anywhere on it; a regular executable file that is neither group- nor
 * other-writable; every ancestor directory not other-writable (sticky
 * excepted) and group-writable only when owned by root.
 */
export function isSafeHelperPath(path: string, fs: HelperFs): boolean {
  if (!isAbsolute(path) || normalize(path) !== path || path.endsWith(sep)) return false
  const file = fs.lstat(path)
  if (file === null || file.isSymbolicLink || !file.isFile) return false
  if (file.mode & (S_IWGRP | S_IWOTH) || !fs.canExecute(path)) return false
  return ancestors(path).every((dir) => {
    const info = fs.lstat(dir)
    return info !== null && !info.isSymbolicLink && info.isDirectory && !replaceableDir(info)
  })
}

export const realHelperFs: HelperFs = {
  lstat: (path) => {
    try {
      const st = lstatSync(path)
      return {
        isFile: st.isFile(),
        isDirectory: st.isDirectory(),
        isSymbolicLink: st.isSymbolicLink(),
        mode: st.mode,
        uid: st.uid
      }
    } catch {
      return null
    }
  },
  canExecute: (path) => {
    try {
      accessSync(path, constants.X_OK)
      return true
    } catch {
      return false
    }
  }
}

/** The real `execFile`, narrowed to the runner's shape. */
export const realTrustExec: TrustExec = (file, args, options, callback) => {
  execFile(file, args, { ...options, encoding: 'utf8' }, (error, stdout) =>
    callback(error, String(stdout))
  )
}
