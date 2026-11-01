// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2 "Main: summon
// snapshot and relay"): what main keeps from the helper's `identify.front` and
// what the renderer may receive — never bounds or documentDir, and for a denied
// app never a pid, window id or title.
import { describe, expect, it } from 'vitest'
import {
  FRONT_NAME_MAX,
  FRONT_TITLE_MAX,
  frontFromIdentify,
  isProjectBoundBundle,
  isSolFrontApp,
  isSolusFront
} from './frontAppShape'

const WINDOW_FRONT = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd',
  bounds: { x: 0, y: 0, width: 800, height: 600 },
  documentDir: 'cad'
}

describe('frontFromIdentify', () => {
  it('keeps exactly the renderer fields of a drivable front', () => {
    expect(frontFromIdentify(WINDOW_FRONT)).toEqual({
      drivable: true,
      binding: 'window',
      bundleId: 'org.freecad.FreeCAD',
      name: 'FreeCAD',
      pid: 4242,
      windowId: 77,
      title: 'bracket_v3.FCStd'
    })
  })

  it('a drivable front without a window keeps null windowId and title', () => {
    const front = { ...WINDOW_FRONT, windowId: null, title: null, bounds: null }
    expect(frontFromIdentify(front)).toMatchObject({ windowId: null, title: null })
  })

  it('a denied app keeps only bundleId, name and drivable:false — whatever else the reply carried', () => {
    const denied = {
      drivable: false,
      binding: null,
      bundleId: 'com.apple.Terminal',
      name: 'Terminal',
      reason: 'denied',
      pid: 9,
      windowId: 3,
      title: 'secret-shell'
    }
    expect(frontFromIdentify(denied)).toEqual({
      drivable: false,
      binding: null,
      bundleId: 'com.apple.Terminal',
      name: 'Terminal'
    })
  })

  it('a project-bound app that cannot drive keeps binding project and no window', () => {
    const kicad = {
      drivable: false,
      binding: 'project',
      bundleId: 'org.kicad.kicad',
      name: 'KiCad',
      reason: 'no_workspace'
    }
    expect(frontFromIdentify(kicad)).toEqual({
      drivable: false,
      binding: 'project',
      bundleId: 'org.kicad.kicad',
      name: 'KiCad'
    })
  })

  it('null front stays null', () => {
    expect(frontFromIdentify(null)).toBeNull()
  })
})

describe('frontFromIdentify — cleaning', () => {
  it('truncates the title to 256 and the name to 64 scalars and drops invisible characters', () => {
    const title = `${'\u0007'}a${String.fromCodePoint(0x200b)}${'é'.repeat(300)}`
    const name = `${'N'.repeat(70)}${String.fromCodePoint(0x202e)}`
    const out = frontFromIdentify({ ...WINDOW_FRONT, title, name })
    expect(out?.drivable).toBe(true)
    if (!out?.drivable) return
    expect([...(out.title ?? '')]).toHaveLength(FRONT_TITLE_MAX)
    expect(out.title?.startsWith('aé')).toBe(true)
    expect([...out.name]).toHaveLength(FRONT_NAME_MAX)
    expect(out.name).toBe('N'.repeat(64))
  })

  it('an emoji title is cut by scalar, never mid-surrogate', () => {
    const out = frontFromIdentify({ ...WINDOW_FRONT, title: '😀'.repeat(300) })
    expect(out?.drivable && [...(out.title ?? '')]).toHaveLength(FRONT_TITLE_MAX)
  })

  it.each([
    ['not an object', 'x'],
    ['bad bundle id', { ...WINDOW_FRONT, bundleId: 'bad id' }],
    ['pid zero', { ...WINDOW_FRONT, pid: 0 }],
    ['pid fractional', { ...WINDOW_FRONT, pid: 1.5 }],
    ['pid over 2^31-1', { ...WINDOW_FRONT, pid: 2 ** 31 }],
    ['negative window id', { ...WINDOW_FRONT, windowId: -1 }],
    ['unknown binding', { ...WINDOW_FRONT, binding: 'global' }],
    ['title not a string', { ...WINDOW_FRONT, title: 5 }],
    ['name missing', { ...WINDOW_FRONT, name: undefined }]
  ])('invalid (%s) → undefined', (_label, front) => {
    expect(frontFromIdentify(front)).toBeUndefined()
  })
})

describe('isSolusFront', () => {
  it.each([
    ['com.solusforge.solus', true],
    ['com.solusforge.solus.helper.Renderer', true],
    ['com.github.Electron', true],
    ['com.github.Electron.helper', true],
    ['com.solusforge.solusx', false],
    ['org.freecad.FreeCAD', false]
  ])('%s → %s (only when denied)', (bundleId, expected) => {
    expect(isSolusFront({ drivable: false, binding: null, bundleId, name: 'x' })).toBe(expected)
  })

  it('a drivable front is never Solus', () => {
    expect(isSolusFront(frontFromIdentify(WINDOW_FRONT) ?? null)).toBe(false)
  })
})

describe('isProjectBoundBundle', () => {
  it('only the two KiCad ids, byte-exact', () => {
    expect(isProjectBoundBundle('org.kicad.kicad')).toBe(true)
    expect(isProjectBoundBundle('org.kicad.eeschema')).toBe(true)
    expect(isProjectBoundBundle('org.kicad.KiCad')).toBe(false)
    expect(isProjectBoundBundle('org.kicad.kicad.x')).toBe(false)
  })
})

describe('isSolFrontApp (preload validator)', () => {
  const ok = frontFromIdentify(WINDOW_FRONT)

  it('accepts what main produces', () => {
    expect(isSolFrontApp(ok)).toBe(true)
    expect(
      isSolFrontApp({ drivable: false, binding: null, bundleId: 'com.apple.mail', name: 'Mail' })
    ).toBe(true)
  })

  it.each([
    [
      'denied carrying a title',
      { drivable: false, binding: null, bundleId: 'a.b', name: 'A', title: 't' }
    ],
    [
      'denied carrying a pid',
      { drivable: false, binding: null, bundleId: 'a.b', name: 'A', pid: 1 }
    ],
    [
      'denied with binding window',
      { drivable: false, binding: 'window', bundleId: 'a.b', name: 'A' }
    ],
    ['title too long', { ...ok, title: 'x'.repeat(FRONT_TITLE_MAX + 1) }],
    ['title with a control char', { ...ok, title: 'a\u0000b' }],
    ['name too long', { ...ok, name: 'x'.repeat(FRONT_NAME_MAX + 1) }],
    ['bounds leaked', { ...ok, bounds: { x: 0 } }],
    ['documentDir leaked', { ...ok, documentDir: 'cad' }],
    ['pid missing', { ...ok, pid: undefined }],
    ['bad bundle', { ...ok, bundleId: '../x' }],
    ['array', []],
    ['null', null]
  ])('rejects %s', (_label, raw) => {
    expect(isSolFrontApp(raw)).toBe(false)
  })
})
