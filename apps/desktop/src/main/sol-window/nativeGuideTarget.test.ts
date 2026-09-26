import { expect, it, vi } from 'vitest'
import { findNativeGuideTarget } from './nativeGuideTarget'
const bounds = { x: 0, y: 0, width: 1920, height: 1080 }
const geometry =
  'Absolute upper-left X: 10\nAbsolute upper-left Y: 20\nWidth: 800\nHeight: 600\nMap State: IsViewable'
function deps(duplicate = false): {
  session: string
  displays: Array<{ id: string; bounds: typeof bounds }>
  read: ReturnType<typeof vi.fn<(file: string, args: string[]) => Promise<string>>>
} {
  return {
    session: 'x11',
    displays: [{ id: '1', bounds }],
    read: vi.fn(async (_file: string, args: string[]) => {
      if (args[0] === '-root')
        return `_NET_CLIENT_LIST(WINDOW): window id # 0x1${duplicate ? ', 0x2' : ''}`
      if (args.includes('WM_CLASS'))
        return 'WM_CLASS(STRING) = "eeschema", "Eeschema"\n_NET_WM_NAME(UTF8_STRING) = "Board"'
      return geometry
    })
  }
}
it('uses fresh visible exact native class geometry and pinned read-only binaries', async () => {
  const fixture = deps()
  expect(await findNativeGuideTarget(fixture)).toEqual({
    tool: 'kicad',
    windowTitle: 'Board',
    displayId: '1',
    bounds: { x: 10, y: 20, width: 800, height: 600 }
  })
  expect(
    fixture.read.mock.calls.every(([file]) =>
      ['/usr/bin/xprop', '/usr/bin/xwininfo'].includes(file)
    )
  ).toBe(true)
})
it('refuses ambiguity, unsupported platforms and windows outside displays', async () => {
  expect(await findNativeGuideTarget(deps(true))).toBeNull()
  const unsupported = { ...deps(), session: 'wayland' }
  expect(await findNativeGuideTarget(unsupported)).toBeNull()
  expect(unsupported.read).not.toHaveBeenCalled()
  expect(await findNativeGuideTarget({ ...deps(), displays: [] })).toBeNull()
})
it('rejects title lookalikes and command failures', async () => {
  const fake = deps()
  fake.read.mockImplementation(async (_file, args) =>
    args[0] === '-root'
      ? '0x1'
      : 'WM_CLASS(STRING) = "evil", "Eeschema-copy"\n_NET_WM_NAME(UTF8_STRING) = "KiCad"'
  )
  expect(await findNativeGuideTarget(fake)).toBeNull()
  fake.read.mockRejectedValue(new Error('timeout'))
  expect(await findNativeGuideTarget(fake)).toBeNull()
})

it('refuses a window that moved while its target was being acquired', async () => {
  const fixture = deps()
  const read = fixture.read.getMockImplementation()!
  let geometries = 0
  fixture.read.mockImplementation(async (file, args) => {
    if (file === '/usr/bin/xwininfo' && ++geometries === 2)
      return geometry.replace('X: 10', 'X: 40')
    return read(file, args)
  })
  expect(await findNativeGuideTarget(fixture)).toBeNull()
})
