// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2 "Relay rule"):
// a window-bound capture/act reaches the agent only when it carries exactly one
// --pid and (--bundle, --pid, --window) equal the summon snapshot; otherwise
// main answers window_mismatch and nothing reaches the agent. KiCad stays
// project-bound (needs --within). A drive child may have no workspace.
import { describe, expect, it, vi } from 'vitest'
import { createDriveRelay, relayRefusal } from './driveRelay'
import type { DriveTransport } from './driveTransport'
import { createFrontAppLink, type FrontAppTracker } from './frontApp'
import type { SolFrontApp } from './frontAppShape'

const WS = '/w/rover'
const SNAPSHOT: SolFrontApp = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd'
}
const BOUND = ['--bundle', 'org.freecad.FreeCAD', '--pid', '4242', '--window', '77']
const CAPTURE = ['capture', ...BOUND, '--max-edge', '1280']
const ACT = ['act', ...BOUND, '--since', '12.5', 'click', '--x', '10', '--y', '20']

describe('relayRefusal — window-bound', () => {
  it.each([
    ['capture, no workspace', CAPTURE, null],
    ['act, no workspace', ACT, null],
    ['capture with the workspace', [...CAPTURE, '--within', WS], WS],
    ['act without --within even when a workspace exists', ACT, WS]
  ])('accepts %s', (_label, argv, workspace) => {
    expect(relayRefusal(argv, workspace, SNAPSHOT)).toBeNull()
  })

  const mismatch = { code: 'window_mismatch', message: expect.any(String) }

  it.each([
    ['no --pid', ['capture', '--bundle', 'org.freecad.FreeCAD', '--window', '77']],
    ['--pid twice', [...CAPTURE, '--pid', '4242']],
    ['another pid', ['capture', '--bundle', 'org.freecad.FreeCAD', '--pid', '1', '--window', '77']],
    [
      'pid with a leading zero',
      ['act', '--bundle', 'org.freecad.FreeCAD', '--pid', '04242', '--window', '77']
    ],
    [
      'another window',
      ['capture', '--bundle', 'org.freecad.FreeCAD', '--pid', '4242', '--window', '78']
    ],
    [
      'another bundle',
      ['capture', '--bundle', 'org.blender.Blender', '--pid', '4242', '--window', '77']
    ]
  ])('refuses window_mismatch: %s', (_label, argv) => {
    expect(relayRefusal(argv, null, SNAPSHOT)).toEqual(mismatch)
  })

  it.each([
    ['no snapshot', null],
    [
      'a denied snapshot',
      { drivable: false, binding: null, bundleId: 'org.freecad.FreeCAD', name: 'F' }
    ],
    ['a project-bound snapshot', { ...SNAPSHOT, binding: 'project' }],
    ['a snapshot without a window', { ...SNAPSHOT, windowId: null }]
  ] as Array<[string, SolFrontApp | null]>)(
    'refuses window_mismatch against %s',
    (_label, front) => {
      expect(relayRefusal(CAPTURE, null, front)).toEqual(mismatch)
    }
  )

  it('a child without a workspace may not send --within at all', () => {
    expect(relayRefusal([...CAPTURE, '--within', WS], null, SNAPSHOT)).toMatchObject({
      code: 'usage'
    })
    expect(relayRefusal(['identify', '--within', WS], null, SNAPSHOT)).toMatchObject({
      code: 'usage'
    })
    expect(relayRefusal(['identify'], null, null)).toBeNull()
  })

  it('KiCad still needs --within, even with a matching snapshot', () => {
    const kicad = ['capture', '--bundle', 'org.kicad.kicad', '--pid', '4242', '--window', '77']
    const front = { ...SNAPSHOT, bundleId: 'org.kicad.kicad' }
    expect(relayRefusal(kicad, null, front)).toMatchObject({ code: 'usage' })
    expect(relayRefusal([...kicad, '--within', WS], WS, front)).toBeNull()
  })

  it('the --flag=value form of a binding flag is malformed (usage)', () => {
    for (const arg of ['--pid=4242', '--window=77', '--bundle=x', '--within=/w']) {
      expect(relayRefusal([...CAPTURE, arg], null, SNAPSHOT)).toMatchObject({ code: 'usage' })
    }
  })

  it('a duplicated --window or --bundle is malformed (usage)', () => {
    expect(relayRefusal([...CAPTURE, '--window', '77'], null, SNAPSHOT)).toMatchObject({
      code: 'usage'
    })
    expect(relayRefusal([...CAPTURE, '--bundle', 'x'], null, SNAPSHOT)).toMatchObject({
      code: 'usage'
    })
  })
})

const tracker = (front: SolFrontApp | null): FrontAppTracker => ({
  beforeSummon: async () => undefined,
  snapshot: () => front,
  clear: () => undefined
})

function harness(front: SolFrontApp | null): {
  relay: ReturnType<typeof createDriveRelay>
  link: ReturnType<typeof createFrontAppLink>
  request: ReturnType<typeof vi.fn<DriveTransport['request']>>
  writes: unknown[]
} {
  const link = createFrontAppLink()
  link.setTracker(tracker(front))
  const request = vi.fn<DriveTransport['request']>(async () => ({ ok: true }))
  const writes: unknown[] = []
  const relay = createDriveRelay({
    packaged: false,
    transport: () => ({ request }),
    write: (_child, line) => void writes.push(JSON.parse(line)),
    frontApp: link
  })
  return { relay, link, request, writes }
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('createDriveRelay — window-bound', () => {
  it('a drive child with no workspace relays a capture that matches the snapshot', async () => {
    const h = harness(SNAPSHOT)
    const child = {}
    h.relay.attach(child, { workspace: null })
    h.relay.request(child, { id: 1, argv: CAPTURE })
    await flush()
    expect(h.request).toHaveBeenCalledWith({ op: 'run', argv: CAPTURE }, expect.anything())
    expect(h.writes).toEqual([{ type: 'drive_reply', id: 1, reply: { ok: true } }])
  })

  it('a mismatched act is answered window_mismatch and never reaches the agent', async () => {
    const h = harness({ ...SNAPSHOT, pid: 1 })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 2, argv: ACT })
    await flush()
    expect(h.request).not.toHaveBeenCalled()
    expect(h.writes).toEqual([
      {
        type: 'drive_reply',
        id: 2,
        reply: { ok: false, code: 'window_mismatch', message: expect.any(String) }
      }
    ])
  })

  it('reports its drive child to the link on attach and detach (clearing the snapshot)', () => {
    const h = harness(SNAPSHOT)
    const setDriveChild = vi.spyOn(h.link, 'setDriveChild')
    const child = {}
    h.relay.attach(child, WS)
    expect(setDriveChild).toHaveBeenLastCalledWith({ workspace: WS })
    h.relay.detach(child)
    expect(setDriveChild).toHaveBeenLastCalledWith(null)
    h.relay.attach({}, null)
    expect(setDriveChild).toHaveBeenLastCalledWith(null)
    h.relay.attach({}, { workspace: null })
    expect(setDriveChild).toHaveBeenLastCalledWith({ workspace: null })
  })

  it('detaching a child that is not current leaves the link alone', () => {
    const h = harness(SNAPSHOT)
    const setDriveChild = vi.spyOn(h.link, 'setDriveChild')
    h.relay.attach({}, WS)
    h.relay.detach({})
    expect(setDriveChild).toHaveBeenCalledTimes(1)
  })
})
