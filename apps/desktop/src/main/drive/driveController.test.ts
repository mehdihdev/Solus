// SOLUSDEV-319 drive slices 3/3b (sol-drive.md §5): the DriveStatus main
// hands the renderer, what the companion and the agent may get, and when.
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
const SOCKET = '/Users/me/Library/Application Support/Solus/drive/agent.sock'

function harness(over: Partial<DriveControllerDeps> = {}): {
  deps: DriveControllerDeps
  setting: { drive: boolean }
  folders: Record<string, string>
  advance(ms: number): void
  broadcasts: DriveStatus[]
  trust: ReturnType<typeof vi.fn>
  companion: ReturnType<typeof vi.fn>
  agentWanted: ReturnType<typeof vi.fn>
} {
  let t = 0
  const setting = { drive: true }
  const listeners = new Set<() => void>()
  const folders: Record<string, string> = { p: '/w/p' }
  const broadcasts: DriveStatus[] = []
  const trust = vi.fn<(prompt: boolean) => Promise<DriveTrustResult | null>>(async () => TRUST)
  const companion = vi.fn()
  const agentWanted = vi.fn()
  const deps: DriveControllerDeps = {
    platform: 'darwin',
    installed: () => true,
    socketPath: () => SOCKET,
    trust,
    agentState: () => 'enabled',
    onAgentWanted: agentWanted,
    linkedFolders: () => ({ ...folders }),
    realpath: (p) => p,
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
    trust,
    companion,
    agentWanted
  }
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('status', () => {
  it('on and available: the agent state and the grants from the agent trust op', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toEqual({
      enabled: true,
      available: true,
      reason: null,
      trust: TRUST.trust,
      unsignedDev: true,
      agent: 'enabled'
    })
    expect(h.trust).toHaveBeenCalledWith(false)
  })

  it('off: available, agent state shown, but the agent is not asked for trust', async () => {
    const h = harness()
    h.setting.drive = false
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toMatchObject({ enabled: false, available: true, trust: null })
    expect(h.trust).not.toHaveBeenCalled()
  })

  it('unavailable: the reason, no trust, no agent state', async () => {
    const h = harness({ platform: 'linux' })
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(await c.status()).toMatchObject({
      available: false,
      reason: 'not_macos',
      trust: null,
      agent: null
    })
    expect(h.trust).not.toHaveBeenCalled()
  })

  it('no_helper when the agent is not installed', async () => {
    const c = createDriveController(harness({ installed: () => false }).deps)
    c.setProject('p')
    expect((await c.status()).reason).toBe('no_helper')
  })

  it('caches trust briefly, then asks again', async () => {
    const h = harness()
    h.trust.mockResolvedValue({ ...TRUST, trust: { accessibility: true, screenRecording: true } })
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    await c.status()
    expect(h.trust).toHaveBeenCalledTimes(1)
    h.advance(DRIVE_TRUST_CACHE_MS)
    await c.status()
    expect(h.trust).toHaveBeenCalledTimes(2)
  })

  it('a missing grant is re-asked on the next status after a short floor (focus refresh)', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status() // TRUST lacks screenRecording
    await c.status() // a render burst shares the cached answer
    expect(h.trust).toHaveBeenCalledTimes(1)
    h.advance(DRIVE_MISSING_GRANT_REFRESH_MS)
    await c.status()
    expect(h.trust).toHaveBeenCalledTimes(2)
  })

  it('a failed trust request reports null trust and is not cached', async () => {
    const h = harness()
    h.trust.mockResolvedValue(null)
    const c = createDriveController(h.deps)
    c.setProject('p') // refresh asks once
    await flush()
    expect(await c.status()).toMatchObject({ available: true, trust: null, unsignedDev: false })
    await c.status()
    expect(h.trust).toHaveBeenCalledTimes(3)
  })
})

describe('companionDrive', () => {
  it('the socket only when the setting is on AND driving is available for that project', () => {
    const h = harness()
    const c = createDriveController(h.deps)
    expect(c.companionDrive('p')).toEqual({ socket: SOCKET })
    expect(c.companionDrive(null)).toBeNull()
    h.folders.q = '/w/p/inner'
    expect(c.companionDrive('p')).toBeNull() // nested_folder
    delete h.folders.q
    h.setting.drive = false
    expect(c.companionDrive('p')).toBeNull()
  })
})

describe('the agent', () => {
  it('wanted while the setting is on and the helper is installed, whatever the project', () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    expect(h.agentWanted).toHaveBeenLastCalledWith(true)
    h.deps.settings.setDrive(false)
    expect(h.agentWanted).toHaveBeenLastCalledWith(false)
    h.deps.settings.setDrive(true)
    h.folders.q = '/w'
    c.refresh()
    expect(h.agentWanted).toHaveBeenLastCalledWith(true) // nested_folder: the project, not the agent
    c.setProject('none')
    expect(h.agentWanted).toHaveBeenLastCalledWith(true) // no_folder: likewise
    expect(c.companionDrive('none')).toBeNull() // …but that project's companion never drives
  })

  it('not wanted when the helper is not installed or not on macOS', () => {
    const missing = harness()
    createDriveController({ ...missing.deps, installed: () => false }).setProject('p')
    expect(missing.agentWanted).toHaveBeenLastCalledWith(false)
    const linux = harness()
    createDriveController({ ...linux.deps, platform: 'linux' }).setProject('p')
    expect(linux.agentWanted).toHaveBeenLastCalledWith(false)
  })
})

describe('changes', () => {
  it('setDrive persists, re-evaluates the companion and broadcasts', async () => {
    const h = harness()
    h.setting.drive = false
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
    h.setting.drive = false
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
})

describe('permissions', () => {
  it('requestPermissions asks the agent with prompt and broadcasts its answer', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    const granted: DriveTrustResult = {
      ...TRUST,
      trust: { accessibility: true, screenRecording: true }
    }
    h.trust.mockResolvedValueOnce(granted)
    const status = await c.requestPermissions()
    expect(h.trust).toHaveBeenLastCalledWith(true)
    expect(status.trust).toEqual(granted.trust)
    await flush()
    expect(h.broadcasts.at(-1)?.trust).toEqual(granted.trust)
  })

  it('the prompt answer is never cached: it predates the grant the user is about to give', async () => {
    const h = harness()
    const c = createDriveController(h.deps)
    c.setProject('p')
    await c.status()
    const calls = h.trust.mock.calls.length
    await c.requestPermissions()
    await c.status() // same instant — still asks again
    expect(h.trust.mock.calls.slice(calls)).toEqual([[true], [false]])
  })

  it('requestPermissions asks nothing while drive is off or unavailable', async () => {
    const off = harness()
    off.setting.drive = false
    const c = createDriveController(off.deps)
    c.setProject('p')
    await c.requestPermissions()
    const linux = harness({ platform: 'win32' })
    const d = createDriveController(linux.deps)
    d.setProject('p')
    expect((await d.requestPermissions()).reason).toBe('not_macos')
    expect(off.trust).not.toHaveBeenCalled()
    expect(linux.trust).not.toHaveBeenCalled()
  })
})
