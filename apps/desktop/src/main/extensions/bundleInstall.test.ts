// SOLUSDEV-235 / EXT-05 — the installer: verify hash → bounded extract into a
// temp dir → rename into place → index update. Every refusal writes NOTHING.
// Archives are real (yauzl over hand-built bytes); the filesystem is a fake,
// plus one real-fs suite for modes and the on-disk rename.
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, test } from 'vitest'
import {
  BUNDLE_LIMITS,
  installBundle,
  uninstallExtension,
  type InstallRequest
} from './bundleInstall'
import { realExtensionFs } from './extensionFs'
import { readExtensionIndex } from './extensionIndex'
import { fakeExtensionFs, seedDir, type FakeExtensionFs } from './testing/fakeExtensionFs'
import {
  buildZip,
  manifestToml,
  S_IFLNK,
  validBundle,
  type ZipEntrySpec
} from './testing/zipBuilder'

const ROOT = '/home/tester/.solus/extensions'
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex')

type RequestOverrides = Partial<{ id: string; version: string; contentHash: string }>

function request(bytes: Uint8Array, over: RequestOverrides = {}): InstallRequest {
  return { id: 'bom', version: '1.2.0', contentHash: sha256(bytes), bytes, ...over }
}

function bundleWith(extra: ZipEntrySpec[], id = 'bom', version = '1.2.0'): Uint8Array {
  return buildZip([{ name: 'extension.toml', data: manifestToml(id, version) }, ...extra])
}

function expectNothingWritten(fs: FakeExtensionFs): void {
  expect(fs.files.size).toBe(0)
  expect([...fs.dirs].filter((d) => d.startsWith(ROOT) && d !== ROOT)).toEqual([])
}

describe('installBundle — happy path', () => {
  test('extracts into <root>/<id>/<version>, 0600 files under 0700 dirs, and records the hash', async () => {
    const fs = fakeExtensionFs()
    const bytes = validBundle()
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: true })
    const dir = `${ROOT}/bom/1.2.0`
    expect(fs.text(`${dir}/widget.html`)).toContain('widget')
    expect(fs.text(`${dir}/assets/app.js`)).toBe('console.log(1)')
    expect(fs.modes.get(`${dir}/widget.html`)).toBe(0o600)
    expect(fs.modes.get(`${dir}/assets`)).toBe(0o700)
    expect(fs.modes.get(`${ROOT}/bom`)).toBe(0o700)
    // No temp directory survives the move.
    expect([...fs.dirs].some((d) => d.includes('.tmp'))).toBe(false)
    expect(readExtensionIndex(fs).index.installed.bom).toEqual({
      version: '1.2.0',
      contentHash: sha256(bytes),
      installedAt: '2026-09-03T12:00:00.000Z',
      source: 'registry'
    })
  })

  test('accepts an upper-case hash from the caller (compared case-insensitively)', async () => {
    const bytes = validBundle()
    const fs = fakeExtensionFs()
    const result = await installBundle(
      request(bytes, { contentHash: sha256(bytes).toUpperCase() }),
      fs
    )
    expect(result).toEqual({ ok: true })
  })

  test('installing a new version removes the previous version directory', async () => {
    const fs = fakeExtensionFs()
    await installBundle(request(validBundle('bom', '1.2.0')), fs)
    const next = validBundle('bom', '1.3.0')
    expect(await installBundle(request(next, { version: '1.3.0' }), fs)).toEqual({ ok: true })
    expect([...fs.dirs].includes(`${ROOT}/bom/1.2.0`)).toBe(false)
    expect(fs.text(`${ROOT}/bom/1.3.0/widget.html`)).toBeDefined()
    expect(readExtensionIndex(fs).index.installed.bom?.version).toBe('1.3.0')
  })

  test('reinstalling the same version replaces the directory in place', async () => {
    const fs = fakeExtensionFs()
    await installBundle(request(validBundle()), fs)
    fs.writeFile(`${ROOT}/bom/1.2.0/stale.html`, 'old', 0o600)
    expect(await installBundle(request(validBundle()), fs)).toEqual({ ok: true })
    expect(fs.files.has(`${ROOT}/bom/1.2.0/stale.html`)).toBe(false)
  })
})

describe('installBundle — refusals write nothing', () => {
  test('hash mismatch', async () => {
    const fs = fakeExtensionFs()
    const result = await installBundle(request(validBundle(), { contentHash: 'b'.repeat(64) }), fs)
    expect(result).toEqual({ ok: false, error: 'hash_mismatch' })
    expectNothingWritten(fs)
  })

  test.each([
    ['unsafe id', { id: 'Bad' }],
    ['reserved id', { id: '__proto__' }],
    ['non-semver version', { version: '1.0' }],
    ['dev as a version', { version: 'dev' }],
    ['malformed hash', { contentHash: 'nope' }]
  ])('invalid request: %s', async (_why, over) => {
    const fs = fakeExtensionFs()
    const result = await installBundle(request(validBundle(), over), fs)
    expect(result).toEqual({ ok: false, error: 'invalid_input' })
    expectNothingWritten(fs)
  })

  test('oversized archive bytes', async () => {
    const fs = fakeExtensionFs()
    const bytes = new Uint8Array(BUNDLE_LIMITS.bytes + 1)
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'too_large' })
    expectNothingWritten(fs)
  })

  test('declared sizes that sum past the cap are refused before extraction', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([
      { name: 'big.bin', data: 'x', deflate: true, declaredSize: BUNDLE_LIMITS.bytes }
    ])
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'too_large' })
    expectNothingWritten(fs)
  })

  test('an entry that inflates past its declared size is refused mid-extract', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([
      { name: 'bomb.bin', data: 'x'.repeat(50_000), deflate: true, declaredSize: 10 }
    ])
    const result = await installBundle(request(bytes), fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(['too_large', 'zip_invalid']).toContain(result.error)
    expectNothingWritten(fs)
  })
})

describe('installBundle — refusals write nothing (entries)', () => {
  test('too many files', async () => {
    const fs = fakeExtensionFs()
    const many = Array.from({ length: BUNDLE_LIMITS.files }, (_, i) => ({
      name: `f${i}.md`,
      data: ''
    }))
    const bytes = bundleWith(many)
    expect(await installBundle(request(bytes), fs)).toEqual({
      ok: false,
      error: 'too_many_entries'
    })
    expectNothingWritten(fs)
  })

  test.each(['../evil.html', '/etc/x.html', 'a\\b.html'])('traversal entry %j', async (name) => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([{ name, data: 'x' }])
    const result = await installBundle(request(bytes), fs)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(['zip_invalid', 'unsafe_entry']).toContain(result.error)
    expectNothingWritten(fs)
  })

  test('an entry name the zip layer tolerates but the contract does not', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([{ name: 'sp ace.html', data: 'x' }])
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'unsafe_entry' })
    expectNothingWritten(fs)
  })

  test('symlink entries are refused (never created)', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([{ name: 'link.html', data: '/etc/passwd', mode: S_IFLNK | 0o777 }])
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'symlink_entry' })
    expectNothingWritten(fs)
  })

  test('duplicate entry names are refused', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([
      { name: 'a.html', data: 'x' },
      { name: 'a.html', data: 'y' }
    ])
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'unsafe_entry' })
    expectNothingWritten(fs)
  })
})

describe('installBundle — refusals write nothing (manifest, index, fs)', () => {
  test('missing manifest', async () => {
    const fs = fakeExtensionFs()
    const bytes = buildZip([{ name: 'widget.html', data: 'x' }])
    expect(await installBundle(request(bytes), fs)).toEqual({
      ok: false,
      error: 'manifest_missing'
    })
    expectNothingWritten(fs)
  })

  test('invalid manifest surfaces the contract problems', async () => {
    const fs = fakeExtensionFs()
    const bytes = bundleWith([], 'Bad Id')
    const result = await installBundle(request(bytes), fs)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toBe('manifest_invalid')
      expect(result.problems?.some((p) => p.startsWith('extension.id:'))).toBe(true)
    }
    expectNothingWritten(fs)
  })

  test('manifest id/version must match the requested id/version', async () => {
    const fs = fakeExtensionFs()
    const other = validBundle('cad', '1.2.0')
    expect(await installBundle(request(other), fs)).toEqual({
      ok: false,
      error: 'manifest_mismatch'
    })
    const otherVersion = validBundle('bom', '9.9.9')
    expect(await installBundle(request(otherVersion), fs)).toEqual({
      ok: false,
      error: 'manifest_mismatch'
    })
    expectNothingWritten(fs)
  })

  test('not a zip', async () => {
    const fs = fakeExtensionFs()
    const bytes = new Uint8Array([80, 75, 3, 4, 0, 0])
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: false, error: 'zip_invalid' })
    expectNothingWritten(fs)
  })

  test('a read-only (newer-schema) index blocks the install and no files land', async () => {
    const fs = fakeExtensionFs()
    fs.writeFile(`${ROOT}/index.json`, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    expect(await installBundle(request(validBundle()), fs)).toEqual({
      ok: false,
      error: 'index_readonly'
    })
    expect([...fs.files.keys()]).toEqual([`${ROOT}/index.json`])
  })

  test('a write failure cleans up the temp dir and reports write_failed', async () => {
    const fs = fakeExtensionFs()
    const write = fs.writeFile
    let writes = 0
    fs.writeFile = (path, data, mode) => {
      if (++writes === 3) throw new Error('ENOSPC')
      write(path, data, mode)
    }
    expect(await installBundle(request(validBundle()), fs)).toEqual({
      ok: false,
      error: 'write_failed'
    })
    expectNothingWritten(fs)
  })
})

describe('uninstallExtension', () => {
  test('removes the extension directory tree and the index entry', async () => {
    const fs = fakeExtensionFs()
    await installBundle(request(validBundle()), fs)
    expect(uninstallExtension('bom', fs)).toEqual({ ok: true })
    expect([...fs.files.keys()].filter((p) => p.startsWith(`${ROOT}/bom`))).toEqual([])
    expect([...fs.dirs].filter((p) => p.startsWith(`${ROOT}/bom`))).toEqual([])
    expect(readExtensionIndex(fs).index.installed.bom).toBeUndefined()
  })

  test('absent is a success; unsafe id is refused; read-only index is refused', async () => {
    const fs = fakeExtensionFs()
    expect(uninstallExtension('ghost', fs)).toEqual({ ok: true })
    expect(uninstallExtension('../x', fs)).toEqual({ ok: false })
    fs.writeFile(`${ROOT}/index.json`, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    seedDir(fs, `${ROOT}/bom/1.0.0`)
    expect(uninstallExtension('bom', fs)).toEqual({ ok: false })
    expect(fs.dirs.has(`${ROOT}/bom/1.0.0`)).toBe(true)
  })
})

describe('real filesystem', () => {
  let dir: string | null = null
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true })
    dir = null
  })

  test('installs on disk with 0700/0600 and uninstalls cleanly', async () => {
    dir = mkdtempSync(join(tmpdir(), 'solus-ext-'))
    const home = dir
    const fs = { ...realExtensionFs, homedir: () => home, warn: () => undefined }
    const bytes = validBundle()
    expect(await installBundle(request(bytes), fs)).toEqual({ ok: true })
    const root = join(home, '.solus', 'extensions')
    const widget = join(root, 'bom', '1.2.0', 'widget.html')
    expect(readFileSync(widget, 'utf8')).toContain('widget')
    expect(readFileSync(join(root, 'bom', '1.2.0', 'assets', 'app.js'), 'utf8')).toBe(
      'console.log(1)'
    )
    if (process.platform !== 'win32') {
      expect(statSync(join(home, '.solus')).mode & 0o777).toBe(0o700)
      expect(statSync(join(root, 'bom', '1.2.0', 'assets')).mode & 0o777).toBe(0o700)
      expect(statSync(widget).mode & 0o777).toBe(0o600)
      expect(statSync(join(root, 'index.json')).mode & 0o777).toBe(0o600)
    }
    expect(readExtensionIndex(fs).index.installed.bom?.contentHash).toBe(sha256(bytes))
    expect(uninstallExtension('bom', fs)).toEqual({ ok: true })
    expect(() => statSync(join(root, 'bom'))).toThrow()
  })
})
