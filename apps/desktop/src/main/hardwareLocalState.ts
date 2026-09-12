// ADR-034: MAIN-owned private source locations, never a shared project payload.
import {
  HARDWARE_LOCAL_STATE_FILENAME,
  HARDWARE_LOCAL_STATE_MAX_BYTES,
  emptyHardwareLocalState,
  parseHardwareLocalState,
  type HardwareLocalAccount,
  type HardwareLocalState
} from '@solus/shared-types'
import { randomUUID } from 'node:crypto'
import {
  constants,
  closeSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
  chmodSync,
  type Stats
} from 'node:fs'
import { join } from 'node:path'

export const HARDWARE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export type HardwareStateRead =
  | { status: 'ready'; state: HardwareLocalState }
  | { status: 'invalid' | 'newer' }
export type HardwareStateWrite =
  | { ok: true }
  | { ok: false; reason: 'invalid' | 'newer' | 'unavailable' }
const EMPTY_ACCOUNT: HardwareLocalAccount = { sources: {}, bindings: {} }
const FILE_MODE = 0o600
const DIRECTORY_MODE = 0o700

function missing(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'code' in error && error.code === 'ENOENT'
}

function sameFile(before: Stats, after: Stats): boolean {
  return (
    after.isFile() &&
    after.ino === before.ino &&
    after.dev === before.dev &&
    after.size === before.size &&
    after.mtimeMs === before.mtimeMs
  )
}

function readBytes(fd: number): Buffer {
  const bytes = Buffer.alloc(HARDWARE_LOCAL_STATE_MAX_BYTES + 1)
  let size = 0
  while (size < bytes.length) {
    const count = readSync(fd, bytes, size, bytes.length - size, null)
    if (!count) break
    size += count
  }
  return bytes.subarray(0, size)
}

function openState(path: string): number | null {
  try {
    return openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
  } catch (error) {
    if (missing(error)) return null
    throw error
  }
}

function removeTemp(temp: string | undefined): void {
  if (temp === undefined) return
  try {
    unlinkSync(temp)
  } catch {
    /* Preserve the original failure. */
  }
}

/** Synchronous read-modify-rename has no event-loop interleaving: all windows use
 * the same MAIN store. Each update re-reads all accounts and preserves other maps.
 * Fork-written state is still untrusted and is validated before every write. */
export class HardwareLocalStore {
  constructor(private readonly home: string) {}

  private directories(projectId: string, create: boolean): string | null {
    if (!HARDWARE_UUID.test(projectId)) throw new Error('invalid project')
    const home = realpathSync(this.home)
    const paths = [
      join(home, '.solus'),
      join(home, '.solus', 'projects'),
      join(home, '.solus', 'projects', projectId)
    ]
    for (const directory of paths) {
      let info
      try {
        info = lstatSync(directory)
      } catch (error) {
        if (!missing(error)) throw error
        if (!create) return null
        mkdirSync(directory, { mode: DIRECTORY_MODE })
        info = lstatSync(directory)
      }
      if (!info.isDirectory() || info.isSymbolicLink() || realpathSync(directory) !== directory) {
        throw new Error('unsafe private directory')
      }
      if (create) chmodSync(directory, DIRECTORY_MODE)
    }
    return paths[2]
  }

  read(projectId: string): HardwareStateRead {
    let fd: number | null = null
    try {
      const directory = this.directories(projectId, false)
      if (directory === null) return { status: 'ready', state: emptyHardwareLocalState() }
      const path = join(directory, HARDWARE_LOCAL_STATE_FILENAME)
      fd = openState(path)
      if (fd === null) return { status: 'ready', state: emptyHardwareLocalState() }
      const info = fstatSync(fd)
      if (!info.isFile() || info.size > HARDWARE_LOCAL_STATE_MAX_BYTES) return { status: 'invalid' }
      const bytes = readBytes(fd)
      if (!this.unchangedFile(projectId, directory, path, info, bytes.length)) {
        return { status: 'invalid' }
      }
      const parsed = parseHardwareLocalState(
        JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
      )
      return parsed.ok ? { status: 'ready', state: parsed.state } : { status: parsed.reason }
    } catch {
      return { status: 'invalid' }
    } finally {
      if (fd !== null) closeSync(fd)
    }
  }

  private unchangedFile(
    projectId: string,
    directory: string,
    path: string,
    before: Stats,
    size: number
  ): boolean {
    const after = lstatSync(path)
    return (
      size <= HARDWARE_LOCAL_STATE_MAX_BYTES &&
      sameFile(before, after) &&
      realpathSync(path) === path &&
      this.directories(projectId, false) === directory
    )
  }

  updateAccount(
    projectId: string,
    accountId: string,
    update: (account: HardwareLocalAccount) => HardwareLocalAccount
  ): HardwareStateWrite {
    if (!HARDWARE_UUID.test(projectId) || !HARDWARE_UUID.test(accountId))
      return { ok: false, reason: 'invalid' }
    const current = this.read(projectId)
    if (current.status !== 'ready') return { ok: false, reason: current.status }
    let content: string
    try {
      const proposed = {
        ...current.state,
        accounts: {
          ...current.state.accounts,
          [accountId]: update(current.state.accounts[accountId] ?? EMPTY_ACCOUNT)
        }
      }
      const parsed = parseHardwareLocalState(proposed)
      if (!parsed.ok) return { ok: false, reason: parsed.reason }
      content = JSON.stringify(parsed.state) + '\n'
      if (Buffer.byteLength(content) > HARDWARE_LOCAL_STATE_MAX_BYTES)
        return { ok: false, reason: 'invalid' }
    } catch {
      return { ok: false, reason: 'unavailable' }
    }
    return this.writeState(projectId, current.state, content)
  }

  private writeState(
    projectId: string,
    current: HardwareLocalState,
    content: string
  ): HardwareStateWrite {
    let temp: string | undefined
    let fd: number | undefined
    try {
      const directory = this.directories(projectId, true)
      if (directory === null) return { ok: false, reason: 'unavailable' }
      temp = join(directory, `.${HARDWARE_LOCAL_STATE_FILENAME}.${randomUUID()}.tmp`)
      fd = openSync(
        temp,
        constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
        FILE_MODE
      )
      writeFileSync(fd, content, 'utf8')
      fsyncSync(fd)
      closeSync(fd)
      fd = undefined
      // Refuse a directory replacement while the temp file was written.
      if (this.directories(projectId, false) !== directory)
        throw new Error('private directory changed')
      const target = join(directory, HARDWARE_LOCAL_STATE_FILENAME)
      const latest = this.read(projectId)
      if (latest.status !== 'ready') return { ok: false, reason: latest.status }
      if (JSON.stringify(latest.state) !== JSON.stringify(current))
        return { ok: false, reason: 'unavailable' }
      renameSync(temp, target)
      temp = undefined
      return { ok: true }
    } catch {
      return { ok: false, reason: 'unavailable' }
    } finally {
      if (fd !== undefined) closeSync(fd)
      removeTemp(temp)
    }
  }
}
