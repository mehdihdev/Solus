// SOLUSDEV-319 drive slice 3 (sol-drive.md §5): where the helper lives, and
// the desktop's own `trust` call — argument list, no shell, bounded, parsed
// defensively.
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import {
  DRIVE_TRUST_MAX_STDOUT,
  DRIVE_TRUST_TIMEOUT_MS,
  isExecutableFile,
  parseTrustOutput,
  resolveDriveHelper,
  runDriveTrust,
  type TrustExec
} from './driveHelper'

describe('resolveDriveHelper', () => {
  it('packaged: the launcher inside <resources>/SolusInput.app', () => {
    expect(
      resolveDriveHelper({
        isPackaged: true,
        resourcesPath: '/Applications/Solus.app/Contents/Resources',
        appPath: '/ignored',
        exists: () => false,
        realpath: (p) => p
      })
    ).toBe(
      '/Applications/Solus.app/Contents/Resources/SolusInput.app/Contents/MacOS/solus-input-launch'
    )
  })

  it('dev: the debug helper found by walking up from the app path', () => {
    const dev = '/repo/apps/desktop/native/solus-input/.build/debug/solus-input'
    expect(
      resolveDriveHelper({
        isPackaged: false,
        resourcesPath: '/ignored',
        appPath: '/repo/apps/desktop/out/main',
        exists: (p) => p === dev,
        realpath: (p) => p
      })
    ).toBe(dev)
  })

  it('dev: resolves the .build/debug symlink, since the companion refuses any symlinked path', () => {
    const dev = '/repo/apps/desktop/native/solus-input/.build/debug/solus-input'
    const real = '/repo/apps/desktop/native/solus-input/.build/out/Products/Debug/solus-input'
    expect(
      resolveDriveHelper({
        isPackaged: false,
        resourcesPath: '',
        appPath: '/repo/apps/desktop',
        exists: (p) => p === dev,
        realpath: (p) => (p === dev ? real : p)
      })
    ).toBe(real)
  })

  it('dev: null when the debug build does not resolve', () => {
    expect(
      resolveDriveHelper({
        isPackaged: false,
        resourcesPath: '',
        appPath: '/repo',
        exists: () => true,
        realpath: () => null
      })
    ).toBeNull()
  })

  it('packaged: never realpath-ed — a planted symlink stays visible to the companion check', () => {
    const realpath = vi.fn((p: string) => `/elsewhere${p}`)
    expect(
      resolveDriveHelper({
        isPackaged: true,
        resourcesPath: '/R',
        appPath: '',
        exists: () => true,
        realpath
      })
    ).toBe('/R/SolusInput.app/Contents/MacOS/solus-input-launch')
    expect(realpath).not.toHaveBeenCalled()
  })

  it('dev: null when no debug build exists', () => {
    expect(
      resolveDriveHelper({
        isPackaged: false,
        resourcesPath: '',
        appPath: '/x',
        exists: () => false,
        realpath: (p) => p
      })
    ).toBeNull()
  })
})

describe('parseTrustOutput', () => {
  const good = {
    ok: true,
    trust: { accessibility: true, screenRecording: false },
    unsignedDev: true
  }

  it('reads the trust grants and the unsigned-dev flag', () => {
    expect(parseTrustOutput(`${JSON.stringify(good)}\n`)).toEqual({
      trust: { accessibility: true, screenRecording: false },
      unsignedDev: true
    })
  })

  it('treats a missing unsignedDev as a signed build', () => {
    const signed = { ok: true, trust: good.trust }
    expect(parseTrustOutput(JSON.stringify(signed))?.unsignedDev).toBe(false)
  })

  it.each([
    ['empty', ''],
    ['not JSON', 'hello'],
    ['an array', '[1]'],
    ['two objects', `${JSON.stringify(good)}\n${JSON.stringify(good)}`],
    ['ok false', JSON.stringify({ ...good, ok: false })],
    ['no trust', JSON.stringify({ ok: true })],
    [
      'a non-boolean grant',
      JSON.stringify({ ...good, trust: { accessibility: 'yes', screenRecording: true } })
    ],
    ['a non-boolean unsignedDev', JSON.stringify({ ...good, unsignedDev: 'true' })]
  ])('null for %s', (_label, raw) => {
    expect(parseTrustOutput(raw)).toBeNull()
  })
})

describe('runDriveTrust', () => {
  const OUT = JSON.stringify({ ok: true, trust: { accessibility: false, screenRecording: false } })

  it('spawns the helper with an argument list, a PATH-only env and the caps', async () => {
    const exec = vi.fn<TrustExec>((_f, _a, _o, cb) => cb(null, OUT))
    const result = await runDriveTrust('/h/solus-input', false, exec)

    expect(result).toEqual({
      trust: { accessibility: false, screenRecording: false },
      unsignedDev: false
    })
    const [file, args, options] = exec.mock.calls[0]
    expect(file).toBe('/h/solus-input')
    expect(args).toEqual(['trust'])
    expect(options).toEqual({
      env: { PATH: '/usr/bin:/bin' },
      timeout: DRIVE_TRUST_TIMEOUT_MS,
      maxBuffer: DRIVE_TRUST_MAX_STDOUT,
      killSignal: 'SIGKILL',
      shell: false,
      windowsHide: true
    })
  })

  it('passes --prompt only when asked', async () => {
    const exec = vi.fn<TrustExec>((_f, _a, _o, cb) => cb(null, OUT))
    await runDriveTrust('/h', true, exec)
    expect(exec.mock.calls[0][1]).toEqual(['trust', '--prompt'])
  })

  it('null on an exec error (timeout, cap, non-zero exit) or a throwing spawn', async () => {
    expect(await runDriveTrust('/h', false, (_f, _a, _o, cb) => cb(new Error('x'), OUT))).toBeNull()
    expect(
      await runDriveTrust('/h', false, () => {
        throw new Error('EACCES')
      })
    ).toBeNull()
  })
})

describe('isExecutableFile', () => {
  it('true only for a regular file with an execute bit', () => {
    const dir = mkdtempSync(join(tmpdir(), 'solus-drive-'))
    try {
      const exe = join(dir, 'exe')
      const plain = join(dir, 'plain')
      writeFileSync(exe, '#!/bin/sh\n', { mode: 0o755 })
      writeFileSync(plain, 'x', { mode: 0o644 })
      expect(isExecutableFile(exe)).toBe(true)
      expect(isExecutableFile(plain)).toBe(false)
      expect(isExecutableFile(dir)).toBe(false)
      expect(isExecutableFile(join(dir, 'missing'))).toBe(false)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
