// SOLUSDEV-235 / EXT-05 — developer mode: an unpacked folder anywhere on disk,
// served in place. Refuses folders whose reach would let solus-ext:// read the
// user's disk (root, home and its ancestors, ~/.solus) and surfaces manifest
// problems verbatim from the contract.
import { createHash } from 'node:crypto'
import { describe, expect, test } from 'vitest'
import { loadDevExtension, removeDevExtension } from './devExtensions'
import { readExtensionIndex, upsertInstalled } from './extensionIndex'
import { MAX_MANIFEST_BYTES } from './manifestToml'
import { fakeExtensionFs, seedDir, seedFile, type FakeExtensionFs } from './testing/fakeExtensionFs'
import { manifestToml } from './testing/zipBuilder'

const ROOT = '/home/tester/.solus/extensions'

function withDevFolder(
  path = '/ws/my-ext',
  toml = manifestToml('my-ext', '0.1.0')
): FakeExtensionFs {
  const fs = fakeExtensionFs()
  seedDir(fs, path)
  seedFile(fs, `${path}/extension.toml`, toml)
  return fs
}

describe('loadDevExtension — folder discipline', () => {
  test.each([
    ['a non-string', 42],
    ['an empty string', ''],
    ['a relative path', 'ws/my-ext'],
    ['a control character', '/ws/my\next'],
    ['a missing folder', '/ws/gone'],
    ['a file, not a directory', '/ws/my-ext/extension.toml'],
    ['the filesystem root', '/'],
    ['the home directory', '/home/tester'],
    ['an ancestor of home', '/home'],
    ['~/.solus itself', '/home/tester/.solus'],
    ['a folder under ~/.solus', `${ROOT}/bom/1.0.0`]
  ])('refuses %s', (_why, path) => {
    const fs = withDevFolder()
    seedDir(fs, '/home/tester/.solus')
    seedDir(fs, `${ROOT}/bom/1.0.0`)
    const result = loadDevExtension(path, fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.problems[0]).toMatch(/^path: /)
    expect(fs.files.has(`${ROOT}/index.json`)).toBe(false)
  })

  test('refuses a symlink that resolves to home (containment runs on the realpath)', () => {
    const fs = withDevFolder()
    fs.links.set('/ws/link-home', '/home/tester')
    expect(loadDevExtension('/ws/link-home', fs).ok).toBe(false)
  })

  test('accepts a normal folder under home and stores the CANONICAL path', () => {
    const fs = withDevFolder('/home/tester/code/my-ext')
    fs.links.set('/ws/alias', '/home/tester/code/my-ext')
    const result = loadDevExtension('/ws/alias', fs)
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.devPath).toBe('/home/tester/code/my-ext')
  })
})

describe('loadDevExtension — manifest', () => {
  test('a valid manifest is parsed and recorded as a dev entry', () => {
    const fs = withDevFolder()
    const result = loadDevExtension('/ws/my-ext', fs)
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.manifest.extension.id).toBe('my-ext')
    const toml = new TextEncoder().encode(manifestToml('my-ext', '0.1.0'))
    expect(readExtensionIndex(fs).index.installed['my-ext']).toEqual({
      version: '0.1.0',
      contentHash: createHash('sha256').update(toml).digest('hex'),
      installedAt: '2026-09-03T12:00:00.000Z',
      source: 'dev',
      devPath: '/ws/my-ext'
    })
  })

  test('missing extension.toml', () => {
    const fs = fakeExtensionFs()
    seedDir(fs, '/ws/empty')
    const result = loadDevExtension('/ws/empty', fs)
    expect(result).toEqual({
      ok: false,
      problems: [expect.stringMatching(/^extension\.toml: missing/)]
    })
  })

  test('a symlinked extension.toml is refused, never followed', () => {
    const fs = withDevFolder()
    fs.links.set('/ws/my-ext/extension.toml', '/etc/secret.toml')
    expect(loadDevExtension('/ws/my-ext', fs).ok).toBe(false)
  })

  test('an oversized manifest is refused before parsing', () => {
    const fs = withDevFolder('/ws/my-ext', 'x'.repeat(MAX_MANIFEST_BYTES + 1))
    const result = loadDevExtension('/ws/my-ext', fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.problems[0]).toMatch(/^extension\.toml: /)
  })

  test('contract problems surface with their dotted paths', () => {
    const fs = withDevFolder('/ws/my-ext', manifestToml('Bad Id', '0.1.0'))
    const result = loadDevExtension('/ws/my-ext', fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.problems.some((p) => p.startsWith('extension.id:'))).toBe(true)
    expect(fs.files.has(`${ROOT}/index.json`)).toBe(false)
  })

  test('a newer manifest schema is refused (this build cannot serve it)', () => {
    const fs = withDevFolder(
      '/ws/my-ext',
      manifestToml().replace('schema_version = 1', 'schema_version = 3')
    )
    expect(loadDevExtension('/ws/my-ext', fs).ok).toBe(false)
  })

  test('a read-only index refuses the load with an index problem', () => {
    const fs = withDevFolder()
    fs.writeFile(`${ROOT}/index.json`, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    const result = loadDevExtension('/ws/my-ext', fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.problems[0]).toMatch(/^index: /)
  })
})

describe('removeDevExtension', () => {
  test('removes a dev entry; absent is a success', () => {
    const fs = withDevFolder()
    loadDevExtension('/ws/my-ext', fs)
    expect(removeDevExtension('my-ext', fs)).toEqual({ ok: true })
    expect(readExtensionIndex(fs).index.installed['my-ext']).toBeUndefined()
    expect(removeDevExtension('my-ext', fs)).toEqual({ ok: true })
  })

  test('refuses a registry entry, an unsafe id, and a read-only index', () => {
    const fs = fakeExtensionFs()
    upsertInstalled(
      'bom',
      { version: '1.0.0', contentHash: 'a'.repeat(64), installedAt: 'x', source: 'registry' },
      fs
    )
    expect(removeDevExtension('bom', fs)).toEqual({ ok: false })
    expect(removeDevExtension('../x', fs)).toEqual({ ok: false })
    fs.writeFile(`${ROOT}/index.json`, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    expect(removeDevExtension('bom', fs)).toEqual({ ok: false })
  })
})
