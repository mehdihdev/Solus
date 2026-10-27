// SOLUSDEV-319 drive slice 3 (sol-drive.md §5): the DriveStatus main hands
// the renderer, what the companion is allowed to get, and when both change.
import { describe, expect, it, vi } from 'vitest'
import {
  createDriveController,
  DRIVE_MISSING_GRANT_REFRESH_MS,
  DRIVE_TRUST_CACHE_MS,
  type DriveControllerDeps
} from './driveController'
import type { DriveTrustResult } from './driveHelper'
import type { DriveStatus } from './driveStatus'

const TRUST: DriveTrustResult = {
  trust: { accessibility: true, screenRecording: false },
  unsignedDev: true
}
const HELPER = '/h/solus-input'

function harness(over: Partial<DriveControllerDeps> = {}): {
  deps: DriveControllerDeps
  setting: { drive: boolean }
  folders: Record<string, string>
  advance(ms: number): void
  broadcasts: DriveStatus[]
  runTrust: ReturnType<typeof vi.fn>
  companion: ReturnType<typeof vi.fn>
} {
  let t = 0
  const setting = { drive: false }
  const listeners = new Set<() => void>()
  const folders: Record<string, string> = { p: '/w/p' }
  const broadcasts: DriveStatus[] = []
  const runTrust = vi.fn(async () => TRUST)
  const companion = vi.fn()
  const deps: DriveControllerDeps = {
    platform: 'darwin',
    helperPath: () => HELPER,
    isExecutable: (p) => p === HELPER,
    linkedFolders: () => ({ ...folders }),
    realpath: (p) => p,
    runTrust,
    settings: {
      get: () => ({ drive: setting.drive }),
      setDrive: (on) => {
        setting.drive = on
        for (const l of listeners) l()
      },
      onChange: (cb) => {
        const l = (): void => cb({ drive: setting.drive })
        listeners.add(l)
        return () => void listeners.delete(l)
      }
    },
    now: () => t,
    broadcast: (s) => void broadcasts.push(s),
    onCompanionDriveChanged: companion,
    ...over
  }
  return {
    deps,
    setting,
    folders,
    advance: (ms) => void (t += ms),
    broadcasts,
    runTrust,
    companion
  }
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('status', () => {
  it('available: runs trust and reports the grants', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toEqual({
      enabled: false,
      available: true,
      reason: null,
      trust: TRUST.trust,
      unsignedDev: true
    })
    expect(h.runTrust).toHaveBeenCalledWith(HELPER, false)
  })

  it('unavailable: the reason, no trust, no spawn', async () => {
    const h = harness({ platform: 'linux' })
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toMatchObject({ available: false, reason: 'not_macos', trust: null })
    expect(h.runTrust).not.toHaveBeenCalled()
  })

  it('no_helper when the path is missing or not executable', async () => {
    const missing = createDriveController(harness({ helperPath: () => null }).deps)
    missing.setProject('p')
    expect((await missing.status()).reason).toBe('no_helper')
    const notExec = createDriveController(harness({ isExecutable: () => false }).deps)
    notExec.setProject('p')
    expect((await notExec.status()).reason).toBe('no_helper')
  })

  it('caches trust briefly, then asks again', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    await c.status()
    expect(h.runTrust).toHaveBeenCalledTimes(1)
    h.advance(DRIVE_TRUST_CACHE_MS)
    await c.status()
    expect(h.runTrust).toHaveBeenCalledTimes(2)
  })

  it('a missing grant is re-asked on the next status after a short floor (focus refresh)', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status() // TRUST lacks screenRecording
    await c.status() // a render burst shares the cached answer
    expect(h.runTrust).toHaveBeenCalledTimes(1)
    h.advance(DRIVE_MISSING_GRANT_REFRESH_MS)
    await c.status()
    expect(h.runTrust).toHaveBeenCalledTimes(2)
  })

  it('full grants stay cached for the whole cache window', async () => {
    const h = harness()
    h.runTrust.mockResolvedValue({
      ...TRUST,
      trust: { accessibility: true, screenRecording: true }
    })
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    h.advance(DRIVE_TRUST_CACHE_MS - 1)
    await c.status()
    expect(h.runTrust).toHaveBeenCalledTimes(1)
  })

  it('a failed trust run reports null trust and is not cached', async () => {
    const h = harness()
    h.runTrust.mockResolvedValueOnce(null)
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toMatchObject({ available: true, trust: null, unsignedDev: false })
    await c.status()
    expect(h.runTrust).toHaveBeenCalledTimes(2)
  })
})

describe('companionDrive', () => {
  it('only when the setting is on AND driving is available for that project', () => {
    const h = harness()
    const c = createDriveController(h.deps)
    expect(c.companionDrive('p')).toBeNull() // setting off
    h.setting.drive = true
    expect(c.companionDrive('p')).toEqual({ helper: HELPER })
    expect(c.companionDrive(null)).toBeNull()
    h.folders.q = '/w/p/inner'
    expect(c.companionDrive('p')).toBeNull() // nested_folder
  })
})

describe('changes', () => {
  it('setDrive persists, re-evaluates the companion and broadcasts', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    const status = await c.setDrive(true)
    expect(status.enabled).toBe(true)
    expect(h.setting.drive).toBe(true)
    expect(h.companion).toHaveBeenCalled()
    await flush()
    expect(h.broadcasts.at(-1)?.enabled).toBe(true)
  })

  it('a setting change from elsewhere (the tray, a file) also propagates', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    h.deps.settings.setDrive(true)
    expect(h.companion).toHaveBeenCalled()
    await flush()
    expect(h.broadcasts.at(-1)?.enabled).toBe(true)
  })

  it('refresh broadcasts only when the status actually changed', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    c.refresh()
    await flush()
    c.refresh()
    await flush()
    expect(h.broadcasts).toHaveLength(1)
    h.folders.q = '/w'
    c.refresh()
    await flush()
    expect(h.broadcasts).toHaveLength(2)
    expect(h.broadcasts[1]).toMatchObject({ available: false, reason: 'nested_folder' })
  })

  it('setProject re-evaluates for the new project', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await flush()
    c.setProject('other')
    await flush()
    expect(h.broadcasts.at(-1)?.reason).toBe('no_folder')
  })

  it('requestPermissions runs trust --prompt, refreshes the cache and broadcasts', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    const granted: DriveTrustResult = {
      ...TRUST,
      trust: { accessibility: true, screenRecording: true }
    }
    h.runTrust.mockResolvedValueOnce(granted)
    const status = await c.requestPermissions()
    expect(h.runTrust).toHaveBeenLastCalledWith(HELPER, true)
    expect(status.trust).toEqual(granted.trust)
    await flush()
    expect(h.broadcasts.at(-1)?.trust).toEqual(granted.trust)
  })

  it('the prompt answer is never cached: it predates the grant the user is about to give', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    const calls = h.runTrust.mock.calls.length
    await c.requestPermissions()
    await c.status() // same instant — still runs a plain trust
    expect(h.runTrust.mock.calls.slice(calls)).toEqual([
      [HELPER, true],
      [HELPER, false]
    ])
  })

  it('requestPermissions does not spawn when unavailable', async () => {
    const h = harness({ platform: 'win32' })
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect((await c.requestPermissions()).reason).toBe('not_macos')
    expect(h.runTrust).not.toHaveBeenCalled()
  })
})
