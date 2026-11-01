// SOLUSDEV-319 slice 4 (API-implementation.md `front_app`): the strict wire
// shape — every key present, explicit nulls, snake_case.
import { describe, expect, it } from 'vitest'
import { toFrontAppBody } from './frontAppBody'

describe('toFrontAppBody', () => {
  it('maps a window-bound drivable app with every key', () => {
    expect(
      toFrontAppBody({
        drivable: true,
        binding: 'window',
        bundleId: 'org.freecad.FreeCAD',
        name: 'FreeCAD',
        pid: 4242,
        windowId: 77,
        title: 'bracket_v3.FCStd'
      })
    ).toEqual({
      bundle_id: 'org.freecad.FreeCAD',
      name: 'FreeCAD',
      title: 'bracket_v3.FCStd',
      pid: 4242,
      window_id: 77,
      drivable: true,
      binding: 'window'
    })
  })

  it('keeps null window id and title as explicit nulls', () => {
    const body = toFrontAppBody({
      drivable: true,
      binding: 'project',
      bundleId: 'org.kicad.kicad',
      name: 'KiCad',
      pid: 9,
      windowId: null,
      title: null
    })
    expect(body).toEqual({
      bundle_id: 'org.kicad.kicad',
      name: 'KiCad',
      title: null,
      pid: 9,
      window_id: null,
      drivable: true,
      binding: 'project'
    })
  })

  it('a denied app sends null title, pid, window id and binding — keys still present', () => {
    const body = toFrontAppBody({
      drivable: false,
      binding: null,
      bundleId: 'com.apple.Terminal',
      name: 'Terminal'
    })
    expect(body).toEqual({
      bundle_id: 'com.apple.Terminal',
      name: 'Terminal',
      title: null,
      pid: null,
      window_id: null,
      drivable: false,
      binding: null
    })
    expect(Object.keys(body).sort()).toEqual([
      'binding',
      'bundle_id',
      'drivable',
      'name',
      'pid',
      'title',
      'window_id'
    ])
  })
})
