// SOLUSDEV-166 (ADR-034) — the ~/.solus project registry, main-process side.
//
// Logic is tested against an in-memory fake of the injected fs surface; one
// small real-fs suite covers what a fake cannot prove (atomic replace on a
// real filesystem, directory modes).
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
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

  // SOLUSDEV-166 security review C1/M4: a forged IPC path must not reach the
  // fork's workspace root. These never occur in a dialog-chosen path.
  test.each([
    ['a NUL byte', '/ws/\x00evil'],
    ['a newline', '/ws/a\nb'],
    ['a cmd.exe ampersand', '/ws/a" & calc "'],
    ['a caret', '/ws/a^b'],
    ['a pipe', '/ws/a|b'],
    ['a redirect', '/ws/a>b'],
    ['a percent (cmd env expansion)', '/ws/%USERPROFILE%'],
    ['a glob star', '/ws/*']
  ])('rejects a path with %s', (_why, path) => {
    const deps = fakeDeps()
    expect(linkProjectFolder('p1', { path }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test('rejects a path that is not an existing directory', () => {
    const deps = fakeDeps({ isDirectory: () => false })
    expect(linkProjectFolder('p1', { path: '/ws/gone' }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
  })

  test.each([
    ['the filesystem root', '/'],
    ['the user home', '/home/tester'],
    ['the home with a trailing slash', '/home/tester/'],
    ['~/.solus itself', HOME]
  ])('refuses %s as a workspace (too much fork reach)', (_why, path) => {
    const deps = fakeDeps()
    expect(linkProjectFolder('p1', { path }, deps)).toBe(false)
    expect(deps.files.size).toBe(0)
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
    expect(written.projects.p1.path).toBe(wsTwo)
    if (process.platform !== 'win32') {
      expect(statSync(solusDir).mode & 0o777).toBe(0o700)
      expect(statSync(file).mode & 0o777).toBe(0o600)
    }
  })
})
