import { describe, it, expect, afterEach } from 'vitest'
import { getDriveBridge } from './driveBridge'
import { fakeDriveBridge } from '../features/settings/drive.fixtures'

function install(sol: unknown): void {
  ;(window as unknown as { solus?: unknown }).solus = { sol }
}

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('getDriveBridge', () => {
  it('is null outside Electron', () => {
    expect(getDriveBridge()).toBeNull()
  })

  it('is null when the SOL bridge has no drive members yet', () => {
    install({ getState: () => null })
    expect(getDriveBridge()).toBeNull()
  })

  it('is null when only some drive members are present', () => {
    const { setDriving, getDriveStatus } = fakeDriveBridge()
    install({ setDriving, getDriveStatus })
    expect(getDriveBridge()).toBeNull()
  })

  it('returns the SOL bridge when every drive member is present', () => {
    const sol = fakeDriveBridge()
    install(sol)
    expect(getDriveBridge()).toBe(sol)
  })
})
