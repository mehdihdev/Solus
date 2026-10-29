// SOLUSDEV-319 drive slices 3/3b (docs/architecture/sol-drive.md §2.1, §5):
// where the helper, the launch agent plist and the XPC module live; the helper
// path rule the dev helper must pass; and the `trust` reply parsing (the
// agent's `trust` op answers the slice 3 shape). Pure except realHelperFs.
import { accessSync, constants, lstatSync } from 'node:fs'
import { dirname, isAbsolute, join, normalize, sep } from 'node:path'
import { findAncestorPath } from '../companionEnv'
import type { DriveTrust } from './driveStatus'

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

export const DRIVE_AGENT_PLIST = 'com.solusforge.solus.input.agent.plist'

export interface DevHelperRuntime {
  /** `app.getAppPath()` — `<repo>/apps/desktop` or a build output under it. */
  appPath: string
  exists: (path: string) => boolean
  /** Canonical path or null. `.build/debug` is a symlink into
   *  `.build/out/Products/Debug`, and the helper path rule refuses symlinks. */
  realpath: (path: string) => string | null
}

/** The dev debug helper main runs as `serve`, or null when there is none. */
export function resolveDevHelper(rt: DevHelperRuntime): string | null {
  const dev = findAncestorPath(rt.appPath, DEV_HELPER, rt.exists)
  return dev === null ? null : rt.realpath(dev)
}

/** What a packaged Solus.app carries for drive: launchd runs `BundleProgram`
 *  (the helper) from the plist SMAppService registers; main talks to it through
 *  the XPC native module (electron-builder mac.extraResources). */
export function packagedDriveFiles(resourcesPath: string): {
  helper: string
  plist: string
  xpcModule: string
} {
  return {
    helper: join(resourcesPath, 'SolusInput.app', 'Contents', 'MacOS', 'solus-input'),
    plist: join(dirname(resourcesPath), 'Library', 'LaunchAgents', DRIVE_AGENT_PLIST),
    xpcModule: join(resourcesPath, 'solus-input-xpc', 'solus_input_xpc.node')
  }
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
 * The helper path rule (mirrors packages/companion drive/helper.py, slice 3),
 * kept for the dev helper main runs as the agent: absolute and normal; no
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
