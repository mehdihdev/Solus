// SOLUSDEV-235 / EXT-05 — the yauzl adapter, driven with hand-built archives.
import { describe, expect, test } from 'vitest'
import { openZip, ZipEntryTooLargeError, ZipReadError } from './zipReader'
import { buildZip, S_IFLNK } from './testing/zipBuilder'

describe('openZip', () => {
  test('lists files, directories, and symlinks with declared sizes', async () => {
    const zip = buildZip([
      { name: 'a.txt', data: 'hello' },
      { name: 'dir/', data: undefined },
      { name: 'link', data: '/etc/passwd', mode: S_IFLNK | 0o777 }
    ])
    const archive = await openZip(zip)
    expect(
      archive.entries.map((e) => [e.name, e.isDirectory, e.isSymlink, e.declaredSize])
    ).toEqual([
      ['a.txt', false, false, 5],
      ['dir/', true, false, 0],
      ['link', false, true, 11]
    ])
  })

  test('reads stored and deflated entries by name', async () => {
    const archive = await openZip(
      buildZip([
        { name: 'a.txt', data: 'hello' },
        { name: 'b.js', data: 'x'.repeat(500), deflate: true }
      ])
    )
    expect(new TextDecoder().decode(await archive.read('a.txt', 1024))).toBe('hello')
    expect((await archive.read('b.js', 1024)).byteLength).toBe(500)
  })

  test('refuses an entry whose declared size exceeds the cap without inflating it', async () => {
    const archive = await openZip(
      buildZip([{ name: 'big.bin', data: 'x'.repeat(4000), deflate: true }])
    )
    await expect(archive.read('big.bin', 100)).rejects.toBeInstanceOf(ZipEntryTooLargeError)
  })

  test('an entry that inflates past its declared size rejects (a header that lies)', async () => {
    const archive = await openZip(
      buildZip([{ name: 'bomb.bin', data: 'x'.repeat(4000), deflate: true, declaredSize: 10 }])
    )
    await expect(archive.read('bomb.bin', 100_000)).rejects.toBeInstanceOf(ZipReadError)
  })

  test('reading an unknown name rejects', async () => {
    const archive = await openZip(buildZip([{ name: 'a.txt', data: 'x' }]))
    await expect(archive.read('nope', 10)).rejects.toThrow()
  })

  test('rejects traversal / absolute / backslash names at the listing', async () => {
    for (const name of ['../evil.html', '/abs.html', 'a\\b.html']) {
      await expect(openZip(buildZip([{ name, data: 'x' }]))).rejects.toThrow()
    }
  })

  test('rejects bytes that are not a zip', async () => {
    await expect(openZip(new Uint8Array([1, 2, 3, 4]))).rejects.toThrow()
  })
})
