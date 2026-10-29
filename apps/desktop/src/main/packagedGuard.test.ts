// ADR-041 amendment 2026-10-28: a packaged Solus.app refuses to start with a
// switch that would let another process drive its main process (a remote
// debugger or inspector), since the drive agent trusts Solus.app's code
// requirement. The fuses block --inspect via the CLI; this covers the rest.
import { describe, expect, it } from 'vitest'
import { FORBIDDEN_PACKAGED_SWITCHES, forbiddenPackagedSwitch } from './packagedGuard'

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
