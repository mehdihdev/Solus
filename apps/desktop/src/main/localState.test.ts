// SOLUSDEV-166 (ADR-034) — the ~/.solus project registry, main-process side.
//
// Logic is tested against an in-memory fake of the injected fs surface; one
// small real-fs suite covers what a fake cannot prove (atomic replace on a
// real filesystem, directory modes).
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, test } from 'vitest'
import {
  folderLinkInput,
  linkProjectFolder,
  projectWorkspace,
  readRegistry,
  realLocalStateDeps,
  solusHomePath,
  unlinkProjectFolder,
  type LocalStateDeps
} from './localState'

/** In-memory deps: a Map of path → content plus a set of directories. */
function fakeDeps(overrides: Partial<LocalStateDeps> = {}): LocalStateDeps & {
  files: Map<string, string>
  modes: Map<string, number>
} {
  const files = new Map<string, string>()
  const modes = new Map<string, number>()
  let suffix = 0
  const deps: LocalStateDeps & { files: Map<string, string>; modes: Map<string, number> } = {
    files,
    modes,
    homedir: () => '/home/tester',
    readFile: (path) => {
      const content = files.get(path)
      if (content === undefined) throw new Error(`ENOENT: ${path}`)
      return content
    },
    writeFile: (path, content, mode) => {
      files.set(path, content)
      modes.set(path, mode)
    },
    replaceFile: (from, to) => {
      const content = files.get(from)
      if (content === undefined) throw new Error(`ENOENT: ${from}`)
      files.set(to, content)
      files.delete(from)
    },
    mkdir: (path, mode) => {
      modes.set(path, mode)
    },
    chmod: (path, mode) => {
      modes.set(path, mode)
    },
    // Default: any absolute path that is not itself a registry file is a real
    // directory. Individual tests override to exercise the not-a-directory path.
    isDirectory: () => true,
    // Default: identity canonicalization (no symlinks/.. in the fake FS).
    // Tests override to exercise `..`/symlink resolution.
    realpath: (path) => path,
    platform: 'linux',
    remove: (path) => {
      files.delete(path)
    },
    tempSuffix: () => `tmp${suffix++}`,
    now: () => new Date('2026-08-30T12:00:00Z'),
    warn: () => undefined,
    ...overrides
  }
  return deps
}

const HOME = '/home/tester/.solus'
const FILE = join(HOME, 'projects.json')

describe('solusHomePath', () => {
  test('is ~/.solus', () => {
    expect(solusHomePath(fakeDeps())).toBe(HOME)
  })
})

describe('readRegistry', () => {
  test('missing file reads as the empty registry, writable', () => {
    expect(readRegistry(fakeDeps())).toEqual({
      registry: { schema_version: 1, projects: {} },
      writable: true
    })
  })

  test('corrupt JSON degrades to empty and stays writable (never crashes)', () => {
    const deps = fakeDeps()
    deps.files.set(FILE, '{ not json')
    const result = readRegistry(deps)
    expect(result.registry.projects).toEqual({})
    expect(result.writable).toBe(true)
  })

  test('invalid shape degrades to empty and stays writable', () => {
    const deps = fakeDeps()
    deps.files.set(FILE, JSON.stringify({ schema_version: 1, projects: { p1: { nope: 1 } } }))
    expect(readRegistry(deps).writable).toBe(true)
  })

  test('a NEWER schema_version is preserved: empty read, NOT writable', () => {
    const deps = fakeDeps()
    deps.files.set(FILE, JSON.stringify({ schema_version: 99, projects: {} }))
    const result = readRegistry(deps)
    expect(result.registry.projects).toEqual({})
    expect(result.writable).toBe(false)
  })

  test('a valid file round-trips', () => {
    const deps = fakeDeps()
    deps.files.set(
      FILE,
      JSON.stringify({ schema_version: 1, projects: { p1: { path: '/ws/rover' } } })
    )
    expect(readRegistry(deps).registry.projects.p1?.path).toBe('/ws/rover')
  })
})

describe('linkProjectFolder', () => {
  test('writes the entry with lastOpenedAt from the clock, atomically via temp+replace', () => {
    const deps = fakeDeps()
    const ok = linkProjectFolder('p1', { path: '/ws/rover', repoUrl: 'https://g/x.git' }, deps)
    expect(ok).toBe(true)
    const written = JSON.parse(deps.files.get(FILE) as string)
    expect(written).toEqual({
      schema_version: 1,
      projects: {
        p1: {
          path: '/ws/rover',
          repoUrl: 'https://g/x.git',
          lastOpenedAt: '2026-08-30T12:00:00.000Z'
        }
      }
    })
    // The temp file is gone (replaced), and nothing else leaked.
    expect([...deps.files.keys()]).toEqual([FILE])
  })

  test('preserves other projects on upsert', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws/rover' }, deps)
    linkProjectFolder('p2', { path: '/ws/arm' }, deps)
    const written = JSON.parse(deps.files.get(FILE) as string)
    expect(Object.keys(written.projects).sort()).toEqual(['p1', 'p2'])
  })

  test('rejects an unsafe project id (path segment discipline)', () => {
    const deps = fakeDeps()
    expect(linkProjectFolder('../evil', { path: '/ws' }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test('rejects an empty or relative path', () => {
    const deps = fakeDeps()
    expect(linkProjectFolder('p1', { path: '' }, deps)).toBe(false)
    expect(linkProjectFolder('p1', { path: 'relative/dir' }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  // Control characters are rejected on EVERY platform: NUL makes spawn throw,
  // a newline corrupts the env line (SOLUSDEV-166 review C1/M4).
  test.each([
    ['a NUL byte', '/ws/\x00evil'],
    ['a newline', '/ws/a\nb'],
    ['a tab', '/ws/a\tb']
  ])('rejects a path with %s on any platform', (_why, path) => {
    for (const platform of ['linux', 'win32'] as const) {
      const deps = fakeDeps({ platform })
      expect(linkProjectFolder('p1', { path }, deps)).toBe(false)
      expect(deps.files.size).toBe(0)
    }
  })

  // The cmd.exe metacharacter class is fatal ONLY on Windows (the launch.cmd
  // sink). On POSIX these are legal directory names the dialog can produce.
  test.each([
    ['an ampersand', '/ws/a & calc'],
    ['a caret', '/ws/a^b'],
    ['a pipe', '/ws/a|b'],
    ['a redirect', '/ws/a>b'],
    ['a percent', '/ws/%USERPROFILE%'],
    ['a glob star', '/ws/proj*']
  ])('rejects %s on Windows but accepts it on POSIX', (_why, path) => {
    const win = fakeDeps({ platform: 'win32' })
    expect(linkProjectFolder('p1', { path }, win)).toBe(false)
    expect(win.files.size).toBe(0)

    const posix = fakeDeps({ platform: 'linux' })
    expect(linkProjectFolder('p1', { path }, posix)).toBe(true)
  })

  test('rejects a path that is not an existing directory', () => {
    const deps = fakeDeps({ isDirectory: () => false })
    expect(linkProjectFolder('p1', { path: '/ws/gone' }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test('rejects a path that does not resolve (realpath null)', () => {
    const deps = fakeDeps({ realpath: () => null })
    expect(linkProjectFolder('p1', { path: '/ws/vanished' }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  // review C1-a: the forbidden set is compared AFTER canonicalization, so
  // dot-segments, doubled separators, and symlinks cannot dodge it.
  test.each([
    ['the filesystem root', '/'],
    ['a doubled-separator root', '//'],
    ['a dot-segment resolving to root', '/tmp/..'],
    ['the user home', '/home/tester'],
    ['the home via a dot-segment', '/home/tester/x/..'],
    ['the home with a trailing slash', '/home/tester/'],
    ['~/.solus itself', HOME],
    ['a path under ~/.solus', `${HOME}/projects/p1`],
    ['a symlink resolving to home', '/ws/link-to-home']
  ])('refuses %s as a workspace (too much fork reach)', (_why, path) => {
    // realpath resolves dot-segments and the symlink fixture to their targets.
    const deps = fakeDeps({
      realpath: (p) => {
        if (p === '/ws/link-to-home') return '/home/tester'
        if (p === '/tmp/..' || p === '//') return '/'
        if (p === '/home/tester/x/..') return '/home/tester'
        return p.replace(/\/+$/, '') || '/'
      }
    })
    expect(linkProjectFolder('p1', { path }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test.each([
    ['the parent of home', '/home'],
    ['a grandparent of home', '/'],
    ['a dot-segment ancestor of home', '/home/tester/..']
  ])('refuses %s — an ancestor of home contains ~/.solus (review C1-a)', (_why, path) => {
    const deps = fakeDeps({
      realpath: (p) => (p === '/home/tester/..' ? '/home' : p.replace(/\/+$/, '') || '/')
    })
    expect(linkProjectFolder('p1', { path }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test('still accepts a normal project directory UNDER home', () => {
    const deps = fakeDeps()
    expect(linkProjectFolder('p1', { path: '/home/tester/robots/rover' }, deps)).toBe(true)
  })

  test('rejects a case-variant of home on a case-insensitive platform', () => {
    const deps = fakeDeps({ platform: 'darwin', realpath: (p) => p })
    expect(linkProjectFolder('p1', { path: '/HOME/TESTER' }, deps)).toBe(false)
  })

  test('rejects a Windows drive root', () => {
    const deps = fakeDeps({
      platform: 'win32',
      homedir: () => 'C:\\Users\\tester',
      realpath: (p) => p
    })
    expect(linkProjectFolder('p1', { path: 'C:\\' }, deps)).toBe(false)
  })

  test('stores the CANONICAL path, not the raw input', () => {
    const deps = fakeDeps({ realpath: (p) => (p === '/ws/link' ? '/ws/real' : p) })
    linkProjectFolder('p1', { path: '/ws/link' }, deps)
    expect(JSON.parse(deps.files.get(FILE) as string).projects.p1.path).toBe('/ws/real')
  })

  // SOLUSDEV-166 security review H2: the registry is fork-readable, so a clone
  // URL's embedded credentials must never be persisted.
  test('strips userinfo from repoUrl before persisting', () => {
    const deps = fakeDeps()
    linkProjectFolder(
      'p1',
      { path: '/ws/rover', repoUrl: 'https://oauth2:glpat-SECRET@gitlab.com/team/rover.git' },
      deps
    )
    const written = JSON.parse(deps.files.get(FILE) as string)
    expect(written.projects.p1.repoUrl).toBe('https://gitlab.com/team/rover.git')
  })

  test('keeps a credential-free scp-style repoUrl unchanged', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws/rover', repoUrl: 'git@gitlab.com:team/rover.git' }, deps)
    const written = JSON.parse(deps.files.get(FILE) as string)
    expect(written.projects.p1.repoUrl).toBe('git@gitlab.com:team/rover.git')
  })

  test('refuses to clobber a registry written by a NEWER schema version', () => {
    const deps = fakeDeps()
    deps.files.set(FILE, JSON.stringify({ schema_version: 99, projects: {} }))
    expect(linkProjectFolder('p1', { path: '/ws' }, deps)).toBe(false)
    expect(JSON.parse(deps.files.get(FILE) as string).schema_version).toBe(99)
  })

  test('creates ~/.solus with 0700 and tightens an existing dir', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws' }, deps)
    expect(deps.modes.get(HOME)).toBe(0o700)
  })
})

describe('unlinkProjectFolder', () => {
  test('removes the entry and keeps the rest', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws/rover' }, deps)
    linkProjectFolder('p2', { path: '/ws/arm' }, deps)
    expect(unlinkProjectFolder('p1', deps)).toBe(true)
    const written = JSON.parse(deps.files.get(FILE) as string)
    expect(Object.keys(written.projects)).toEqual(['p2'])
  })

  test('unlinking an absent project is a no-op success', () => {
    expect(unlinkProjectFolder('ghost', fakeDeps())).toBe(true)
  })

  test('rejects an unsafe project id', () => {
    expect(unlinkProjectFolder('../evil', fakeDeps())).toBe(false)
  })

  test.each([['__proto__'], ['constructor'], ['prototype']])(
    'rejects the reserved id %j at the write boundary',
    (projectId) => {
      const deps = fakeDeps()
      expect(linkProjectFolder(projectId, { path: '/ws' }, deps)).toBe(false)
      expect(unlinkProjectFolder(projectId, deps)).toBe(false)
      expect(deps.files.size).toBe(0)
    }
  )

  test('a reserved-id link cannot poison the registry (review L7 write path)', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws/rover' }, deps)
    expect(linkProjectFolder('__proto__', { path: '/ws/evil' }, deps)).toBe(false)
    // p1 survives and the registry still reads back cleanly.
    expect(readRegistry(deps).registry.projects.p1?.path).toBe('/ws/rover')
  })
})

describe('projectWorkspace', () => {
  test('resolves the linked path for the companion spawn', () => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws/rover' }, deps)
    expect(projectWorkspace('p1', deps)).toBe('/ws/rover')
  })

  test('null when unlinked, null project, or unsafe id', () => {
    const deps = fakeDeps()
    expect(projectWorkspace('p1', deps)).toBeNull()
    expect(projectWorkspace(null, deps)).toBeNull()
    expect(projectWorkspace('../evil', deps)).toBeNull()
  })

  // review C1-b: the registry file is fork-writable, so the stored value is
  // re-validated at the sink. A hostile/hand-edited path yields null and the
  // fork fails closed.
  test.each([
    ['a cmd.exe metacharacter', '/ws" & calc & "', 'win32'],
    ['the filesystem root', '/', 'linux'],
    ['the user home', '/home/tester', 'linux'],
    ['a NUL byte', '/ws/\x00x', 'linux']
  ])('returns null for a stored %s', (_why, path, platform) => {
    const deps = fakeDeps({ platform: platform as NodeJS.Platform })
    // Plant the hostile value directly on disk, bypassing the write guard.
    deps.files.set(FILE, JSON.stringify({ schema_version: 1, projects: { p1: { path } } }))
    expect(projectWorkspace('p1', deps)).toBeNull()
  })
})

describe('repo URL credential handling (SOLUSDEV-166 review H2)', () => {
  test.each([
    ['https userinfo', 'https://oauth2:glpat-X@gitlab.com/t/r.git', 'https://gitlab.com/t/r.git'],
    ['https token as user', 'https://ghp_TOKEN@github.com/o/r.git', 'https://github.com/o/r.git'],
    ['scp-style (no credential)', 'git@github.com:team/rover.git', 'git@github.com:team/rover.git'],
    ['ssh with required git user', 'ssh://git@github.com/o/r.git', 'ssh://git@github.com/o/r.git']
  ])('%s → keeps it usable without leaking a secret', (_why, input, expected) => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws', repoUrl: input }, deps)
    expect(JSON.parse(deps.files.get(FILE) as string).projects.p1.repoUrl).toBe(expected)
  })

  test.each([
    ['opaque-scheme token', 'oauth2:TOKEN@github.com'],
    ['x-access-token opaque form', 'x-access-token:ghp_SECRET@github.com/o/r.git']
  ])('drops a credential-bearing non-URL value entirely (%s)', (_why, input) => {
    const deps = fakeDeps()
    linkProjectFolder('p1', { path: '/ws', repoUrl: input }, deps)
    expect(JSON.parse(deps.files.get(FILE) as string).projects.p1.repoUrl).toBeUndefined()
  })

  test('a legacy registry credential is stripped on read (review H2-c)', () => {
    const deps = fakeDeps()
    deps.files.set(
      FILE,
      JSON.stringify({
        schema_version: 1,
        projects: { p1: { path: '/ws', repoUrl: 'https://oauth2:glpat-X@gitlab.com/t/r.git' } }
      })
    )
    expect(readRegistry(deps).registry.projects.p1?.repoUrl).toBe('https://gitlab.com/t/r.git')
  })
})

describe('folderLinkInput — untrusted renderer input for folder:link', () => {
  test('accepts a minimal and a full link, picking ONLY the known fields', () => {
    expect(folderLinkInput({ path: '/ws' })).toEqual({ path: '/ws' })
    expect(folderLinkInput({ path: '/ws', repoUrl: 'https://g/x.git', evil: 'x' })).toEqual({
      path: '/ws',
      repoUrl: 'https://g/x.git'
    })
  })

  test.each([
    ['null', null],
    ['a string', '/ws'],
    ['an array', ['/ws']],
    ['a missing path', { repoUrl: 'r' }],
    ['an empty path', { path: '' }],
    ['a non-string path', { path: 7 }],
    ['a non-string repoUrl', { path: '/ws', repoUrl: 7 }]
  ])('rejects %s', (_why, value) => {
    expect(folderLinkInput(value)).toBeNull()
  })
})

describe('real filesystem deps', () => {
  let dir: string | null = null
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true })
    dir = null
  })

  test('writes atomically under a 0700 home and replaces an existing file', () => {
    dir = mkdtempSync(join(tmpdir(), 'solus-localstate-'))
    const home = dir
    // Real workspaces must be real directories now (isDirectory guard).
    const wsOne = join(dir, 'one')
    const wsTwo = join(dir, 'two')
    mkdirSync(wsOne)
    mkdirSync(wsTwo)
    const deps: LocalStateDeps = { ...realLocalStateDeps, homedir: () => home }
    expect(linkProjectFolder('p1', { path: wsOne }, deps)).toBe(true)
    expect(linkProjectFolder('p1', { path: wsTwo }, deps)).toBe(true)
    const solusDir = join(home, '.solus')
    const file = join(solusDir, 'projects.json')
    const written = JSON.parse(readFileSync(file, 'utf8'))
    // The stored value is canonical (realpath resolves e.g. /var → /private/var).
    expect(written.projects.p1.path).toBe(realpathSync.native(wsTwo))
    if (process.platform !== 'win32') {
      expect(statSync(solusDir).mode & 0o777).toBe(0o700)
      expect(statSync(file).mode & 0o777).toBe(0o600)
    }
  })
})
