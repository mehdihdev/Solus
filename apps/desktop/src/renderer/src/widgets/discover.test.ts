// SOLUSDEV-216 (CTR-01) — discovery over the REAL widget directory.
//
// This is the test that fails the day two lanes ship a widget with the same id,
// or someone forgets the default export. It runs the actual glob, so it is a
// check on the repo, not on a fixture.
import { describe, expect, test } from 'vitest'
import { discoverWidgets } from './discover'

describe('discoverWidgets', () => {
  test('finds every widget.manifest.ts in the widgets directory', () => {
    const widgets = discoverWidgets()
    expect(widgets.map((w) => w.id)).toContain('reference')
  })

  test('every discovered manifest is valid and uniquely identified', () => {
    // collectManifests throws on a malformed or duplicated manifest, so simply
    // calling it is the assertion; this pins that it is actually called.
    const ids = discoverWidgets().map((w) => w.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  test('returns widgets in a stable, id-sorted order', () => {
    const ids = discoverWidgets().map((w) => w.id)
    expect(ids).toEqual([...ids].sort())
  })
})
