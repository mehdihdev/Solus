// SOLUSDEV-249 (I2) — this machine's identity for local-folder sources.
//
// The id must be the companion's `~/.solus/companion_id` byte for byte
// (`load_instance_id`: uuid4().hex, mode 0600 under a 0700 home), so whichever
// process runs first, both agree. Tested against an in-memory fs fake.
import { describe, expect, it } from 'vitest'
import {
  INSTANCE_ID_PATTERN,
  instanceIdPath,
  machineIdentity,
  machineName,
  readOrCreateInstanceId,
  realMachineIdentityDeps,
  type MachineIdentityDeps
} from './machineIdentity'
import { realLocalStateDeps } from './localState'

const FRESH_ID = '0123456789abcdef0123456789abcdef'

const ID_PATH = '/home/tester/.solus/companion_id'

function fakeDeps(overrides: Partial<MachineIdentityDeps> = {}): MachineIdentityDeps & {
  files: Map<string, string>
  modes: Map<string, number>
  /** Every path `writeFile` opened, in order — proves the target itself never is. */
  opened: string[]
  symlinks: Set<string>
} {
  const files = new Map<string, string>()
  const modes = new Map<string, number>()
  const opened: string[] = []
  const symlinks = new Set<string>()
  let suffix = 0
  return {
    files,
    modes,
    opened,
    symlinks,
    homedir: () => '/home/tester',
    readFile: (path) => {
      const content = files.get(path)
      if (content === undefined) throw new Error(`ENOENT: ${path}`)
      return content
    },
    writeFile: (path, content, mode) => {
      opened.push(path)
      files.set(path, content)
      modes.set(path, mode)
    },
    replaceFile: (from, to) => {
      const content = files.get(from)
      if (content === undefined) throw new Error(`ENOENT: ${from}`)
      files.set(to, content)
      modes.set(to, modes.get(from) ?? 0)
      files.delete(from)
      symlinks.delete(to) // rename replaces a link at `to`; it never follows it
    },
    remove: (path) => {
      files.delete(path)
    },
    tempSuffix: () => `tmp${suffix++}`,
    mkdir: (path, mode) => {
      modes.set(path, mode)
    },
    chmod: (path, mode) => {
      modes.set(path, mode)
    },
    isSymlink: (path) => symlinks.has(path),
    newInstanceId: () => FRESH_ID,
    hostname: () => 'mehdi-mbp',
    ...overrides
  }
}

describe('readOrCreateInstanceId', () => {
  it('reads the companion-written id when present, writing nothing', () => {
    const deps = fakeDeps()
    const existing = 'fedcba9876543210fedcba9876543210'
    deps.files.set('/home/tester/.solus/companion_id', `${existing}\n`)

    expect(readOrCreateInstanceId(deps)).toBe(existing)
    expect(deps.modes.size).toBe(0)
  })

  it('creates the id the companion way when absent: 32 hex, mode 0600 under a 0700 home', () => {
    const deps = fakeDeps()

    const id = readOrCreateInstanceId(deps)

    expect(id).toBe(FRESH_ID)
    expect(deps.files.get(ID_PATH)).toBe(FRESH_ID)
    expect(deps.modes.get(ID_PATH)).toBe(0o600)
    expect(deps.modes.get('/home/tester/.solus')).toBe(0o700)
  })

  it('writes atomically: only a temp file is ever opened, then renamed over the target', () => {
    const deps = fakeDeps()

    readOrCreateInstanceId(deps)

    expect(deps.opened).toEqual([`${ID_PATH}.tmp0.tmp`])
    expect(deps.files.has(`${ID_PATH}.tmp0.tmp`)).toBe(false) // no temp litter
    expect(deps.files.get(ID_PATH)).toBe(FRESH_ID)
  })

  it('removes the temp file when the replace fails, and surfaces the failure', () => {
    const deps = fakeDeps({
      replaceFile: () => {
        throw new Error('EPERM')
      }
    })
    expect(() => readOrCreateInstanceId(deps)).toThrow('EPERM')
    expect(deps.files.size).toBe(0)
  })

  it('refuses a symlinked companion_id: neither read through nor written through', () => {
    const deps = fakeDeps()
    deps.symlinks.add(ID_PATH)
    // What the link points at holds a well-formed id — it must still not be trusted.
    deps.files.set(ID_PATH, 'fedcba9876543210fedcba9876543210')

    expect(readOrCreateInstanceId(deps)).toBeNull()
    expect(machineIdentity(deps)).toBeNull()
    expect(deps.opened).toEqual([])
    expect(deps.files.get(ID_PATH)).toBe('fedcba9876543210fedcba9876543210') // untouched
    expect(deps.modes.size).toBe(0)
  })

  it('rewrites a malformed file rather than trusting it', () => {
    const deps = fakeDeps()
    deps.files.set(ID_PATH, 'not-hex')

    expect(readOrCreateInstanceId(deps)).toBe(FRESH_ID)
    expect(deps.files.get(ID_PATH)).toBe(FRESH_ID)
  })

  it('is stable across calls once created', () => {
    let n = 0
    const deps = fakeDeps({ newInstanceId: () => `${n++}`.padStart(32, 'a') })
    expect(readOrCreateInstanceId(deps)).toBe(readOrCreateInstanceId(deps))
  })

  it('resolves the file under ~/.solus', () => {
    expect(instanceIdPath(fakeDeps())).toBe('/home/tester/.solus/companion_id')
  })
})

describe('machineIdentity', () => {
  it('pairs the instance id with the hostname', () => {
    expect(machineIdentity(fakeDeps())).toEqual({ id: FRESH_ID, name: 'mehdi-mbp' })
    expect(machineName({ hostname: () => 'lab-01' })).toBe('lab-01')
  })

  it('production deps mint ids in the companion shape', () => {
    const id = realMachineIdentityDeps.newInstanceId()
    expect(id).toMatch(INSTANCE_ID_PATTERN)
    expect(realMachineIdentityDeps.newInstanceId()).not.toBe(id)
    expect(realMachineIdentityDeps.hostname()).toEqual(expect.any(String))
    // An absent path is not a symlink; the write goes through the registry's helper.
    expect(realMachineIdentityDeps.isSymlink('/nonexistent/solus/companion_id')).toBe(false)
    expect(realMachineIdentityDeps.replaceFile).toBe(realLocalStateDeps.replaceFile)
  })
})
