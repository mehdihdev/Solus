// SOLUSDEV-252 S3: best-effort foreground window (docs/architecture/
// sol-window.md §6) — X11 via pinned xprop argument lists; null everywhere else.
import { describe, it, expect, vi } from 'vitest'
import { activeWindow, XPROP, type ActiveWindowDeps } from './activeWindow'
import type { PlatformBasics } from '../platform/capabilities'

const X11: PlatformBasics = { platform: 'linux', arch: 'arm64', session: 'x11' }

function fakeExec(answers: Record<string, string | Error>): {
  deps: ActiveWindowDeps
  calls: Array<{ file: string; args: string[]; timeoutMs: number }>
} {
  const calls: Array<{ file: string; args: string[]; timeoutMs: number }> = []
  return {
    calls,
    deps: {
      execFile: async (file, args, timeoutMs) => {
        calls.push({ file, args, timeoutMs })
        const a = answers[args.join(' ')]
        if (a instanceof Error) throw a
        if (a === undefined) throw new Error('unexpected call')
        return a
      }
    }
  }
}

describe('activeWindow on X11', () => {
  it('resolves app (WM_CLASS class) and title through two pinned xprop calls', async () => {
    const f = fakeExec({
      '-root _NET_ACTIVE_WINDOW': '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007\n',
      '-id 0x3a00007 WM_CLASS _NET_WM_NAME':
        'WM_CLASS(STRING) = "onshape", "Google-chrome"\n_NET_WM_NAME(UTF8_STRING) = "Arm v2 — Onshape"\n'
    })
    await expect(activeWindow(X11, f.deps)).resolves.toEqual({
      app: 'Google-chrome',
      title: 'Arm v2 — Onshape'
    })
    expect(f.calls.map((c) => c.file)).toEqual([XPROP, XPROP])
    expect(f.calls.every((c) => c.timeoutMs === 500)).toBe(true)
  })

  it('a missing binary (ENOENT) or a timeout → null, never a throw', async () => {
    const f = fakeExec({ '-root _NET_ACTIVE_WINDOW': new Error('ENOENT') })
    await expect(activeWindow(X11, f.deps)).resolves.toBeNull()
  })

  it('no active window (0x0) → null without a second call', async () => {
    const f = fakeExec({
      '-root _NET_ACTIVE_WINDOW': '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n'
    })
    await expect(activeWindow(X11, f.deps)).resolves.toBeNull()
    expect(f.calls).toHaveLength(1)
  })

  it('unparseable output → null', async () => {
    const f = fakeExec({
      '-root _NET_ACTIVE_WINDOW': '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x1\n',
      '-id 0x1 WM_CLASS _NET_WM_NAME': 'WM_CLASS: not found.\n'
    })
    await expect(activeWindow(X11, f.deps)).resolves.toBeNull()
  })
})

it('darwin / win32 / wayland → null without running anything (documented gap)', async () => {
  const exec = vi.fn()
  for (const basics of [
    { platform: 'darwin', arch: 'arm64', session: 'macos' },
    { platform: 'win32', arch: 'x64', session: 'windows' },
    { platform: 'linux', arch: 'x64', session: 'wayland' }
  ] as PlatformBasics[]) {
    await expect(activeWindow(basics, { execFile: exec })).resolves.toBeNull()
  }
  expect(exec).not.toHaveBeenCalled()
})
