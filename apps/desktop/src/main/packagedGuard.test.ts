// ADR-041 amendment 2026-10-28: a packaged Solus.app refuses to start with a
// switch that would let another process drive its main process (a remote
// debugger or inspector), since the drive agent trusts Solus.app's code
// requirement. The fuses block --inspect via the CLI; this covers the rest.
import { describe, expect, it } from 'vitest'
import {
  FORBIDDEN_PACKAGED_SWITCHES,
  forbiddenPackagedSwitch,
  packagedLaunchRefusal
} from './packagedGuard'

const none = (): boolean => false

describe('forbiddenPackagedSwitch', () => {
  it('lists the switches the amendment names', () => {
    expect([...FORBIDDEN_PACKAGED_SWITCHES].sort()).toEqual(
      [
        'inspect',
        'inspect-brk',
        'inspect-port',
        'js-flags',
        'remote-debugging-pipe',
        'remote-debugging-port'
      ].sort()
    )
  })

  it('null for a clean packaged launch, and always in dev', () => {
    expect(
      forbiddenPackagedSwitch({ isPackaged: true, argv: ['/A/Solus'], hasSwitch: none })
    ).toBeNull()
    expect(
      forbiddenPackagedSwitch({
        isPackaged: false,
        argv: ['electron', '--remote-debugging-port=9333'],
        hasSwitch: () => true
      })
    ).toBeNull()
  })

  it('found through app.commandLine.hasSwitch', () => {
    const hasSwitch = (name: string): boolean => name === 'remote-debugging-pipe'
    expect(forbiddenPackagedSwitch({ isPackaged: true, argv: [], hasSwitch })).toBe(
      'remote-debugging-pipe'
    )
  })

  it.each([
    ['--remote-debugging-port=9222'],
    ['--remote-debugging-port'],
    ['--inspect'],
    ['--inspect=0.0.0.0:9229'],
    ['--inspect-brk'],
    ['--inspect-port=1'],
    ['--js-flags=--allow-natives-syntax'],
    ['-inspect'] // Chromium also accepts a single dash
  ])('found in argv: %s', (arg) => {
    expect(
      forbiddenPackagedSwitch({ isPackaged: true, argv: ['/A/Solus', arg], hasSwitch: none })
    ).not.toBeNull()
  })

  it('a look-alike argument is not a switch', () => {
    expect(
      forbiddenPackagedSwitch({
        isPackaged: true,
        argv: ['/A/Solus', '--inspector-theme=dark', 'solus://open?inspect=1'],
        hasSwitch: none
      })
    ).toBeNull()
  })
})

// Review MEDIUM-2: on macOS a packaged launch takes an argv ALLOWLIST — the
// executable, macOS's -psn_* and at most one solus:// URL — because Chromium
// has many switches that run another program (or code) inside Solus.app.
describe('packagedLaunchRefusal', () => {
  const EXE = '/Applications/Solus.app/Contents/MacOS/Solus'
  const launch = (
    args: string[],
    over: Partial<{ isPackaged: boolean; platform: NodeJS.Platform }> = {}
  ): string | null =>
    packagedLaunchRefusal({
      isPackaged: true,
      platform: 'darwin',
      argv: [EXE, ...args],
      hasSwitch: none,
      ...over
    })

  it.each([[[]], [['-psn_0_123']], [['solus://x']], [['-psn_0_123', 'solus://open?p=1']]])(
    'allows %j',
    (args) => {
      expect(launch(args)).toBeNull()
    }
  )

  it.each([
    ['--browser-subprocess-path=/tmp/x'],
    ['--renderer-cmd-prefix=/tmp/x'],
    ['--gpu-launcher=/tmp/x'],
    ['--utility-cmd-prefix=/tmp/x'],
    ['--remote-debugging-address=0.0.0.0'],
    ['--foo'],
    ['plain-argument'],
    ['https://solusforge.com'],
    ['-psn_x'],
    ['--remote-debugging-port=9222']
  ])('refuses %s', (arg) => {
    expect(launch([arg])).not.toBeNull()
  })

  it('refuses a second solus:// URL', () => {
    expect(launch(['solus://a', 'solus://b'])).not.toBeNull()
  })

  it('keeps the hasSwitch belt even with a clean argv', () => {
    expect(
      packagedLaunchRefusal({
        isPackaged: true,
        platform: 'darwin',
        argv: [EXE],
        hasSwitch: (n) => n === 'remote-debugging-pipe'
      })
    ).toBe('--remote-debugging-pipe')
  })

  it('dev is never refused; other packaged platforms keep the denylist only', () => {
    expect(launch(['--foo'], { isPackaged: false })).toBeNull()
    expect(launch(['--no-sandbox'], { platform: 'linux' })).toBeNull()
    expect(launch(['--inspect'], { platform: 'linux' })).not.toBeNull()
  })

  it('never echoes a whole argument (it may carry a path or a URL)', () => {
    expect(launch(['--renderer-cmd-prefix=/Users/me/secret/x'])).toBe('--renderer-cmd-prefix')
    expect(launch(['plain-argument'])).toBe('an unexpected argument')
  })
})
