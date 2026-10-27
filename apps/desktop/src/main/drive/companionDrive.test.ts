// SOLUSDEV-319 drive slice 3, review M3: the companion's drive lifecycle
// decisions, extracted from companion.ts so they are tested without a process.
import { describe, expect, it, vi } from 'vitest'
import { createDriveGeometryRelay, driveRespawnNeeded, folderChangeAction } from './companionDrive'

const B = { x: 1, y: 2, width: 3, height: 4 }

describe('driveRespawnNeeded', () => {
  it('respawns a running child only when its baked helper differs', () => {
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: null }, '/h')).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: '/h' }, null)).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: '/h' }, '/other')).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: '/h' }, '/h')).toBe(false)
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: null }, null)).toBe(false)
  })

  it('never with no child: the next spawn reads the fresh decision anyway', () => {
    expect(driveRespawnNeeded({ hasChild: false, bakedHelper: null }, '/h')).toBe(false)
    expect(driveRespawnNeeded({ hasChild: true, bakedHelper: undefined }, '/h')).toBe(false)
  })
})

describe('folderChangeAction', () => {
  const base = { activeProjectId: 'a', workspaceNow: '/w/a', workspaceBaked: '/w/a' }

  it('respawns when the active project workspace changed', () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'a', workspaceNow: '/w/new' })).toBe(
      'respawn'
    )
  })

  it("re-checks drive for ANOTHER project's link change (the nested-folder rule)", () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'b' })).toBe('recheck_drive')
  })

  it('re-checks drive (only) when the active link was rewritten to the same path', () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'a' })).toBe('recheck_drive')
  })

  it('nothing without an active project', () => {
    expect(folderChangeAction({ ...base, activeProjectId: null, changedProjectId: 'a' })).toBe(
      'none'
    )
  })
})

describe('createDriveGeometryRelay', () => {
  it('forwards geometry only from the current child, spawned with drive', () => {
    const listener = vi.fn()
    const relay = createDriveGeometryRelay()
    relay.setListener(listener)
    const withDrive = {}
    const without = {}
    const onWithout = relay.attach(without, false)
    onWithout(B)
    expect(listener).not.toHaveBeenCalled() // spawned without drive: ignored
    const onWith = relay.attach(withDrive, true)
    onWithout(B) // the old child is no longer current
    onWith(B)
    expect(listener.mock.calls).toEqual([[B]])
  })

  it('detach (exit, replace, stop) clears the outline with null — for the current child only', () => {
    const listener = vi.fn()
    const relay = createDriveGeometryRelay()
    relay.setListener(listener)
    const old = {}
    const current = {}
    relay.attach(old, true)
    const onCurrent = relay.attach(current, true)
    relay.detach(old)
    expect(listener).not.toHaveBeenCalled()
    relay.detach(current)
    expect(listener.mock.calls).toEqual([[null]])
    onCurrent(B) // late output from a detached child
    expect(listener.mock.calls).toEqual([[null]])
  })

  it('a null listener is safe', () => {
    const relay = createDriveGeometryRelay()
    const child = {}
    relay.attach(child, true)(B)
    expect(() => relay.detach(child)).not.toThrow()
  })
})
