// SOLUSDEV-319 A3b (sol-drive.md §2.2, ADR-041 2026-10-31 "window-bound driving
// without a workspace"): the supervisor attaches drive to a child whether or
// not the project has a linked folder, and every transition between drive off,
// on-without-folder and on-with-folder replaces the running child. A real,
// harmless child (`sleep 30`) is spawned; the relay and the registry are mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({
  app: { isPackaged: false, getPath: () => '/tmp/solus-test', getAppPath: () => '/tmp/solus-test' }
}))

const registry = vi.hoisted(() => ({ folder: null as string | null }))
vi.mock('./localState', () => ({
  projectWorkspace: (projectId: string | null) => (projectId ? registry.folder : null),
  realLocalStateDeps: {}
}))

const relay = vi.hoisted(() => ({
  attach: vi.fn(),
  detach: vi.fn(),
  request: vi.fn(),
  cancel: vi.fn()
}))
vi.mock('./drive/driveRelay', () => ({ createDriveRelay: () => relay }))

type Companion = typeof import('./companion')
const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

let companion: Companion
let driveOn = false

beforeEach(async () => {
  registry.folder = null
  driveOn = false
  relay.attach.mockClear()
  process.env.SOLUS_COMPANION_DEV_CMD = 'sleep 30'
  delete process.env.SOLUS_COMPANION_WORKSPACE
  vi.resetModules()
  companion = await import('./companion')
  companion.setCompanionDriveResolver(() => driveOn)
  companion.startCompanion()
})

afterEach(async () => {
  await companion.stopCompanion()
  delete process.env.SOLUS_COMPANION_DEV_CMD
})

/** The drive argument of every attach so far. */
const attached = (): unknown[] => relay.attach.mock.calls.map(([, drive]) => drive)
/** Let a coalesced replacement land. */
const settle = (): Promise<void> => wait(companion.REPLACE_COALESCE_MS + 150)

describe('companion supervisor — drive attach (A3b)', () => {
  it('drive on, no folder: attaches {workspace: null} with a relay gate', () => {
    driveOn = true
    companion.setCompanionProject('project-a')

    expect(attached()).toEqual([{ workspace: null }])
    expect(relay.attach.mock.calls[0][2]).toBeInstanceOf(Promise)
  })

  it('drive on, folder linked: attaches {workspace: folder}', () => {
    driveOn = true
    registry.folder = '/w'
    companion.setCompanionProject('project-a')

    expect(attached()).toEqual([{ workspace: '/w' }])
  })

  it('drive off: attaches null and no gate', () => {
    registry.folder = '/w'
    companion.setCompanionProject('project-a')

    expect(attached()).toEqual([null])
    expect(relay.attach.mock.calls[0][2]).toBeUndefined()
  })
})

describe('companion supervisor — drive respawn (A3b)', () => {
  it('off → on with no folder respawns with {workspace: null}', async () => {
    companion.setCompanionProject('project-a')
    driveOn = true
    companion.notifyCompanionDriveChanged()
    await settle()

    expect(attached()).toEqual([null, { workspace: null }])
  })

  it('on with no folder → off respawns without drive', async () => {
    driveOn = true
    companion.setCompanionProject('project-a')
    driveOn = false
    companion.notifyCompanionDriveChanged()
    await settle()

    expect(attached()).toEqual([{ workspace: null }, null])
  })

  it('on with no folder → folder linked respawns with the folder', async () => {
    driveOn = true
    companion.setCompanionProject('project-a')
    registry.folder = '/w'
    companion.notifyProjectFolderChanged('project-a')
    await settle()

    expect(attached()).toEqual([{ workspace: null }, { workspace: '/w' }])
  })

  it('on with a folder → folder unlinked respawns, still driving', async () => {
    driveOn = true
    registry.folder = '/w'
    companion.setCompanionProject('project-a')
    registry.folder = null
    companion.notifyProjectFolderChanged('project-a')
    await settle()

    expect(attached()).toEqual([{ workspace: '/w' }, { workspace: null }])
  })

  it('on with a folder → off respawns without drive', async () => {
    driveOn = true
    registry.folder = '/w'
    companion.setCompanionProject('project-a')
    driveOn = false
    companion.notifyCompanionDriveChanged()
    await settle()

    expect(attached()).toEqual([{ workspace: '/w' }, null])
  })

  it.each([
    ['off', false, null],
    ['on, no folder', true, null],
    ['on, folder', true, '/w']
  ])('an unchanged decision (%s) does not respawn', async (_label, on, folder) => {
    driveOn = on
    registry.folder = folder
    companion.setCompanionProject('project-a')
    companion.notifyCompanionDriveChanged()
    companion.notifyProjectFolderChanged('project-b') // another project's link
    await settle()

    expect(relay.attach).toHaveBeenCalledTimes(1)
  })
})
