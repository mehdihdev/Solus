import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { ToolWindowRef, WindowBounds } from '@solus/shared-types'
import { parseWindowInfo } from '../capture/activeWindow'

interface TargetDeps {
  session: string
  displays: Array<{ id: string; bounds: WindowBounds }>
  read(file: string, args: string[]): Promise<string>
}
const XPROP = '/usr/bin/xprop'
const XWININFO = '/usr/bin/xwininfo'
const CLASSES = new Set(['eeschema'])
const execute = promisify(execFile)
export async function readNativeWindowProperty(file: string, args: string[]): Promise<string> {
  return (
    await execute(file, args, {
      timeout: 500,
      maxBuffer: 16_384,
      encoding: 'utf8',
      windowsHide: true
    })
  ).stdout
}
function geometry(raw: string): WindowBounds | null {
  if (!raw.includes('Map State: IsViewable')) return null
  const fields = ['Absolute upper-left X', 'Absolute upper-left Y', 'Width', 'Height']
  const values = fields.map((field) =>
    Number(new RegExp(`${field}:\\s*(-?\\d+)`).exec(raw)?.[1] ?? NaN)
  )
  if (!values.every(Number.isSafeInteger)) return null
  const [x, y, width, height] = values
  return width > 0 && height > 0 && width <= 16384 && height <= 16384
    ? { x, y, width, height }
    : null
}
function contains(display: WindowBounds, window: WindowBounds): boolean {
  return (
    window.x >= display.x &&
    window.y >= display.y &&
    window.x + window.width <= display.x + display.width &&
    window.y + window.height <= display.y + display.height
  )
}
/** No pixels, shell, renderer-controlled command strings or guessed coordinates. */
export async function findNativeGuideTarget(deps: TargetDeps): Promise<ToolWindowRef | null> {
  if (deps.session !== 'x11') return null
  try {
    const list = await deps.read(XPROP, ['-root', '_NET_CLIENT_LIST'])
    if (list.length > 16_384) return null
    const ids = [...new Set(list.match(/0x[0-9a-f]+/gi) ?? [])]
    if (ids.length > 16) return null
    const candidates = await Promise.all(
      ids.map(async (id): Promise<ToolWindowRef | null> => {
        const props = await deps.read(XPROP, ['-id', id, 'WM_CLASS', '_NET_WM_NAME'])
        if (props.length > 16_384) return null
        const info = parseWindowInfo(props)
        if (!info || !CLASSES.has(info.app.toLowerCase()) || info.title.length > 256) return null
        const raw = await deps.read(XWININFO, ['-id', id])
        const bounds = raw.length <= 16_384 ? geometry(raw) : null
        if (!bounds) return null
        const display = deps.displays.find((candidate) => contains(candidate.bounds, bounds))
        if (!display) return null
        // Reject windows moved, closed or replaced while this observation was acquired.
        const again = await deps.read(XPROP, ['-id', id, 'WM_CLASS', '_NET_WM_NAME'])
        const fresh = geometry(await deps.read(XWININFO, ['-id', id]))
        if (again !== props || JSON.stringify(fresh) !== JSON.stringify(bounds)) return null
        return { tool: 'kicad', windowTitle: info.title, displayId: display.id, bounds }
      })
    )
    const matches = candidates.filter((item) => item !== null)
    return matches.length === 1 ? matches[0] : null
  } catch {
    return null
  }
}
