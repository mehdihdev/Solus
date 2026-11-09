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

const realArgv = process.argv
afterEach(() => {
  process.argv = realArgv
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

  it('exits for an argument outside the macOS allowlist', async () => {
    if (process.platform !== 'darwin') return
    electron.app.commandLine.hasSwitch.mockImplementation(() => false)
    process.argv = ['/A/Solus', '--renderer-cmd-prefix=/tmp/x']
    const exit = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never)
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    await import('./packagedGuardBoot')
    expect(exit).toHaveBeenCalledWith(1)
  })

  it('does nothing for a clean launch', async () => {
    electron.app.commandLine.hasSwitch.mockImplementation(() => false)
    process.argv = ['/A/Solus']
    const exit = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never)
    await import('./packagedGuardBoot')
    expect(electron.app.exit).not.toHaveBeenCalled()
    expect(exit).not.toHaveBeenCalled()
  })
})
