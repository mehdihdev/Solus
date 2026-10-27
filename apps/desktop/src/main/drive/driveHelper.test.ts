// SOLUSDEV-319 drive slices 3/3b (sol-drive.md §2.1, §5): where the helper,
// the agent plist and the socket live, the helper path rule, and the `trust`
// reply parsing (the agent's `trust` op answers the same shape).
import { describe, expect, it } from 'vitest'
import {
  driveSocketPaths,
  isSafeHelperPath,
  packagedDriveFiles,
  parseTrustOutput,
  realHelperFs,
  resolveDevHelper,
  type HelperFs
} from './driveHelper'

describe('resolveDevHelper', () => {
  const dev = '/repo/apps/desktop/native/solus-input/.build/debug/solus-input'

  it('the debug helper found by walking up from the app path', () => {
    expect(
      resolveDevHelper({
        appPath: '/repo/apps/desktop/out/main',
        exists: (p) => p === dev,
        realpath: (p) => p
      })
    ).toBe(dev)
  })

  it('resolves the .build/debug symlink, since the helper path rule refuses any symlink', () => {
    const real = '/repo/apps/desktop/native/solus-input/.build/out/Products/Debug/solus-input'
    expect(
      resolveDevHelper({
        appPath: '/repo/apps/desktop',
        exists: (p) => p === dev,
        realpath: (p) => (p === dev ? real : p)
      })
    ).toBe(real)
  })

  it('null when no debug build exists or it does not resolve', () => {
    expect(resolveDevHelper({ appPath: '/x', exists: () => false, realpath: (p) => p })).toBeNull()
    expect(resolveDevHelper({ appPath: '/x', exists: () => true, realpath: () => null })).toBeNull()
  })
})

// Slice 3b (sol-drive.md §5 "Available"): `no_helper` means the agent is not
// installed — packaged: SolusInput.app's helper or the LaunchAgents plist is
// missing from the bundle; dev: the debug helper is missing or fails the rule.
describe('packagedDriveFiles', () => {
  it('the helper inside Resources and the plist in Contents/Library/LaunchAgents', () => {
    expect(packagedDriveFiles('/Applications/Solus.app/Contents/Resources')).toEqual({
      helper:
        '/Applications/Solus.app/Contents/Resources/SolusInput.app/Contents/MacOS/solus-input',
      plist:
        '/Applications/Solus.app/Contents/Library/LaunchAgents/com.solusforge.solus.input.agent.plist'
    })
  })
})

describe('driveSocketPaths', () => {
  it('packaged uses drive/, dev uses drive-dev/ so the two never collide', () => {
    expect(driveSocketPaths({ isPackaged: true, home: '/Users/me' })).toEqual({
      dir: '/Users/me/Library/Application Support/Solus/drive',
      socket: '/Users/me/Library/Application Support/Solus/drive/agent.sock'
    })
    expect(driveSocketPaths({ isPackaged: false, home: '/Users/me' }).socket).toBe(
      '/Users/me/Library/Application Support/Solus/drive-dev/agent.sock'
    )
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

// Mirrors the companion's helper rule (drive/helper.py resolve_helper) so
// Settings never says "available" for a path the companion would refuse.
describe('isSafeHelperPath', () => {
  type Node = { kind: 'file' | 'dir' | 'link'; mode: number; uid: number }
  const fsWith = (nodes: Record<string, Node>, executable = true): HelperFs => ({
    lstat: (p) => {
      const n = nodes[p]
      if (!n) return null
      return {
        isFile: n.kind === 'file',
        isDirectory: n.kind === 'dir',
        isSymbolicLink: n.kind === 'link',
        mode: n.mode,
        uid: n.uid
      }
    },
    canExecute: () => executable
  })
  const root = { kind: 'dir', mode: 0o755, uid: 0 } as const
  const HELPER = '/Applications/Solus.app/Contents/MacOS/solus-input-launch'
  const tree = (over: Record<string, Partial<Node>> = {}): Record<string, Node> => {
    const base: Record<string, Node> = {
      '/': { ...root },
      // /Applications is root:admin 0775 on a stock Mac.
      '/Applications': { kind: 'dir', mode: 0o775, uid: 0 },
      '/Applications/Solus.app': { kind: 'dir', mode: 0o755, uid: 501 },
      '/Applications/Solus.app/Contents': { kind: 'dir', mode: 0o755, uid: 501 },
      '/Applications/Solus.app/Contents/MacOS': { kind: 'dir', mode: 0o755, uid: 501 },
      [HELPER]: { kind: 'file', mode: 0o755, uid: 501 }
    }
    for (const [p, n] of Object.entries(over)) base[p] = { ...base[p], ...n } as Node
    return base
  }

  it('accepts a stock install, a root-owned group-writable ancestor included', () => {
    expect(isSafeHelperPath(HELPER, fsWith(tree()))).toBe(true)
  })

  it('refuses a user-owned group-writable ancestor', () => {
    const fs = fsWith(tree({ '/Applications/Solus.app/Contents': { mode: 0o775 } }))
    expect(isSafeHelperPath(HELPER, fs)).toBe(false)
  })

  it('refuses an other-writable ancestor, but not a sticky one', () => {
    expect(isSafeHelperPath(HELPER, fsWith(tree({ '/Applications': { mode: 0o777 } })))).toBe(false)
    expect(isSafeHelperPath(HELPER, fsWith(tree({ '/Applications': { mode: 0o1777 } })))).toBe(true)
  })

  it('refuses a group- or other-writable helper file', () => {
    expect(isSafeHelperPath(HELPER, fsWith(tree({ [HELPER]: { mode: 0o775 } })))).toBe(false)
    expect(isSafeHelperPath(HELPER, fsWith(tree({ [HELPER]: { mode: 0o757 } })))).toBe(false)
  })

  it('refuses a symlink anywhere on the path', () => {
    expect(isSafeHelperPath(HELPER, fsWith(tree({ [HELPER]: { kind: 'link' } })))).toBe(false)
    const fs = fsWith(tree({ '/Applications/Solus.app/Contents': { kind: 'link' } }))
    expect(isSafeHelperPath(HELPER, fs)).toBe(false)
  })

  it('refuses a relative, non-normal, missing, non-file or non-executable path', () => {
    const fs = fsWith(tree())
    expect(isSafeHelperPath('Applications/x', fs)).toBe(false)
    expect(
      isSafeHelperPath('/Applications/Solus.app/../Solus.app/Contents/MacOS/solus-input-launch', fs)
    ).toBe(false)
    expect(isSafeHelperPath('/Applications/Solus.app/Contents/MacOS/missing', fs)).toBe(false)
    expect(isSafeHelperPath('/Applications/Solus.app/Contents/MacOS', fs)).toBe(false)
    expect(isSafeHelperPath(HELPER, fsWith(tree(), false))).toBe(false)
  })

  it('the real fs answers false for a missing path without throwing', () => {
    expect(isSafeHelperPath('/definitely/not/here/solus-input', realHelperFs)).toBe(false)
  })
})
