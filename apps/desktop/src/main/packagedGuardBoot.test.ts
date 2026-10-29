// The boot module exits a packaged launch carrying a forbidden switch, and does
// nothing otherwise.
import { afterEach, describe, expect, it, vi } from 'vitest'

const electron = vi.hoisted(() => ({
  app: {
    isPackaged: true,
    exit: vi.fn(),
    commandLine: { hasSwitch: vi.fn<(name: string) => boolean>(() => false) }
  }
}))
vi.mock('electron', () => electron)

afterEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  electron.app.exit.mockClear()
})

describe('packagedGuardBoot', () => {
  it('exits when a forbidden switch is present', async () => {
    electron.app.commandLine.hasSwitch.mockImplementation((n) => n === 'remote-debugging-port')
    const exit = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never)
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    await import('./packagedGuardBoot')
    expect(electron.app.exit).toHaveBeenCalledWith(1)
    expect(exit).toHaveBeenCalledWith(1)
  })

  it('does nothing for a clean launch', async () => {
    electron.app.commandLine.hasSwitch.mockImplementation(() => false)
    const exit = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never)
    await import('./packagedGuardBoot')
    expect(electron.app.exit).not.toHaveBeenCalled()
    expect(exit).not.toHaveBeenCalled()
  })
})
