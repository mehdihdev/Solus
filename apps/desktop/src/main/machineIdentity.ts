// This machine's identity for local-folder sources (SOLUSDEV-249 / I2).
//
// The companion persists its instance id in `~/.solus/companion_id`
// (`solus_companion.config.load_instance_id`: `uuid4().hex`, file mode 0600
// under the 0700 `~/.solus`). The API pins every local source to that id and
// checks the live bridge session carries the same one, so the desktop must
// read the SAME file — and, when it runs first, create it the SAME way, so
// whichever process wins the race the two agree. The machine name is the
// hostname: display only, never an identity.
//
// The fs surface is injected (localState.ts idiom) so the decisions here are
// unit-testable without a real filesystem.
//
// Security (SOLUSDEV-249 review): `~/.solus` is writable by anything running
// as the user, so a symlink pre-planted at `companion_id` must never be
// followed — neither read through nor written through. The write goes via the
// registry's atomic temp+replace helper, which never opens the target itself.
import { SOLUS_HOME_MODE } from '@solus/shared-types'
import { randomUUID } from 'node:crypto'
import { lstatSync } from 'node:fs'
import { hostname } from 'node:os'
import { join } from 'node:path'
import {
  realLocalStateDeps,
  solusHomePath,
  writeFileAtomically,
  type LocalStateDeps
} from './localState'

export const COMPANION_ID_FILENAME = 'companion_id'
/** Owner read/write only — mirrors the companion's `os.open(..., 0o600)`. */
const INSTANCE_FILE_MODE = 0o600
/** The shape both sides accept; anything else is rewritten (companion parity). */
export const INSTANCE_ID_PATTERN = /^[0-9a-f]{32}$/

export type MachineIdentityDeps = Pick<
  LocalStateDeps,
  'homedir' | 'readFile' | 'writeFile' | 'replaceFile' | 'remove' | 'tempSuffix' | 'mkdir' | 'chmod'
> & {
  /** `lstat` says the path itself is a symlink (false when absent). */
  isSymlink: (path: string) => boolean
  /** 32 lowercase hex chars — `uuid4().hex` on the companion side. */
  newInstanceId: () => string
  hostname: () => string
}

export interface MachineIdentity {
  id: string
  name: string
}

export function instanceIdPath(deps: MachineIdentityDeps): string {
  return join(solusHomePath(deps), COMPANION_ID_FILENAME)
}

/** Read the persisted instance id, or create one exactly as the companion
 *  does. Null when the path is a symlink: it is neither trusted nor replaced
 *  (someone planted it), and the caller reports the machine as id-less. */
export function readOrCreateInstanceId(deps: MachineIdentityDeps): string | null {
  const path = instanceIdPath(deps)
  if (deps.isSymlink(path)) return null
  try {
    const existing = deps.readFile(path).trim()
    if (INSTANCE_ID_PATTERN.test(existing)) return existing
  } catch {
    /* absent or unreadable — create below */
  }
  const id = deps.newInstanceId()
  const home = solusHomePath(deps)
  deps.mkdir(home, SOLUS_HOME_MODE)
  deps.chmod(home, SOLUS_HOME_MODE) // a pre-existing looser dir is tightened too
  writeFileAtomically(path, id, INSTANCE_FILE_MODE, deps)
  return id
}

export function machineName(deps: Pick<MachineIdentityDeps, 'hostname'>): string {
  return deps.hostname()
}

export function machineIdentity(deps: MachineIdentityDeps): MachineIdentity | null {
  const id = readOrCreateInstanceId(deps)
  return id === null ? null : { id, name: machineName(deps) }
}

export const realMachineIdentityDeps: MachineIdentityDeps = {
  homedir: realLocalStateDeps.homedir,
  readFile: realLocalStateDeps.readFile,
  writeFile: realLocalStateDeps.writeFile,
  replaceFile: realLocalStateDeps.replaceFile,
  remove: realLocalStateDeps.remove,
  tempSuffix: realLocalStateDeps.tempSuffix,
  mkdir: realLocalStateDeps.mkdir,
  chmod: realLocalStateDeps.chmod,
  isSymlink: (path) => {
    try {
      return lstatSync(path).isSymbolicLink()
    } catch {
      return false
    }
  },
  newInstanceId: () => randomUUID().replace(/-/g, ''),
  hostname
}
