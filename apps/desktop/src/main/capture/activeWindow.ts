// SOLUSDEV-252 S3: best-effort foreground window {app, title} (docs/architecture/
// sol-window.md §6). X11 only: two `xprop` calls with ARGUMENT LISTS on a pinned
// path (CLAUDE.md §7 subprocess rule), 500 ms each; a missing binary, a timeout
// or unparseable output → null. The result is untrusted input to the model
// layer downstream — it is fenced as data there, never interpreted here.
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { PlatformBasics } from '../platform/capabilities'

export const XPROP = '/usr/bin/xprop'
const XPROP_TIMEOUT_MS = 500

export interface ActiveWindowDeps {
  /** Run `file` with `args`, resolving stdout; rejects on any failure. */
  execFile(file: string, args: string[], timeoutMs: number): Promise<string>
}

export interface ActiveWindowInfo {
  app: string
  title: string
}

const unquote = (s: string): string => s.replace(/\\(["\\])/g, '$1')

/** `xprop -root _NET_ACTIVE_WINDOW` → the window id, or null for none (0x0). */
export function parseActiveWindowId(root: string): string | null {
  const id = /window id # (0x[0-9a-f]+)/i.exec(root)?.[1]
  return !id || /^0x0+$/.test(id) ? null : id
}

/** `xprop -id <id> WM_CLASS _NET_WM_NAME` → { app, title }, or null when neither parses. */
export function parseWindowInfo(props: string): ActiveWindowInfo | null {
  const cls = /WM_CLASS\(STRING\) = (.*)$/m.exec(props)?.[1]
  const name = /_NET_WM_NAME\(UTF8_STRING\) = "((?:[^"\\]|\\.)*)"/m.exec(props)?.[1]
  if (cls === undefined && name === undefined) return null
  // WM_CLASS is `"instance", "Class"` — the class is the app name.
  const classes = [...(cls ?? '').matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => unquote(m[1]))
  return { app: classes.at(-1) ?? '', title: name === undefined ? '' : unquote(name) }
}

export async function activeWindow(
  basics: PlatformBasics,
  deps: ActiveWindowDeps
): Promise<ActiveWindowInfo | null> {
  // ponytail: darwin/win32 have no shipped native module for this in S3 — null,
  // and the region card simply omits its caption (documented gap, §6).
  if (basics.session !== 'x11') return null
  try {
    const root = await deps.execFile(XPROP, ['-root', '_NET_ACTIVE_WINDOW'], XPROP_TIMEOUT_MS)
    const id = parseActiveWindowId(root)
    if (id === null) return null
    const props = await deps.execFile(
      XPROP,
      ['-id', id, 'WM_CLASS', '_NET_WM_NAME'],
      XPROP_TIMEOUT_MS
    )
    return parseWindowInfo(props)
  } catch {
    return null
  }
}

const execFileAsync = promisify(execFile)

export const realActiveWindowDeps: ActiveWindowDeps = {
  execFile: async (file, args, timeout) =>
    (await execFileAsync(file, args, { timeout, encoding: 'utf8', windowsHide: true })).stdout
}
