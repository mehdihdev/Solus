// SOLUSDEV-246 / STORE ST3 — in-context widget suggestions: only what a newly
// connected source unlocks, never what is installed, never what sells.
import { describe, it, expect } from 'vitest'
import { newlyConnectedKinds, suggestionsAfterConnect, suggestionToast } from './suggestions'
import { catalogItem, installRow, manifest } from './testing/fixtures'

const bom = catalogItem({
  slug: 'bom',
  name: 'BOM',
  summary: 'Bill of materials.',
  requires: [['eda', 'cad']]
})
const experiments = catalogItem({
  slug: 'experiments',
  name: 'Experiments',
  summary: 'Runs on the robot.',
  requires: [['runtime']]
})
const anytime = catalogItem({ slug: 'notes', name: 'Notes', requires: [] })

describe('newlyConnectedKinds', () => {
  it('names the kinds that appeared, mapping source types to kinds', () => {
    expect(newlyConnectedKinds(['github'], ['github', 'kicad'])).toEqual(['eda'])
    expect(newlyConnectedKinds(['kicad'], ['kicad', 'altium'])).toEqual([])
    expect(newlyConnectedKinds([], ['ros', 'onshape'])).toEqual(['cad', 'runtime'])
  })
})

describe('suggestionsAfterConnect', () => {
  it('suggests the widget an EDA tool unlocks, not the always-available one', () => {
    const out = suggestionsAfterConnect({
      catalog: [bom, experiments, anytime],
      installs: [],
      beforeTypes: ['github'],
      afterTypes: ['github', 'kicad']
    })
    expect(out.map((s) => [s.view.catalog.slug, s.unlockedBy])).toEqual([['bom', ['eda']]])
  })

  it('suggests Experiments when a robot connects', () => {
    const out = suggestionsAfterConnect({
      catalog: [bom, experiments],
      installs: [],
      beforeTypes: [],
      afterTypes: ['ros']
    })
    expect(out.map((s) => s.view.catalog.slug)).toEqual(['experiments'])
  })

  it('never suggests what is already installed, blocked, or was available before', () => {
    const installed = installRow({
      version: {
        ...installRow().version,
        manifest: manifest({ extension: { ...manifest().extension, id: 'bom', name: 'BOM' } })
      }
    })
    expect(
      suggestionsAfterConnect({
        catalog: [bom],
        installs: [installed],
        beforeTypes: [],
        afterTypes: ['kicad']
      })
    ).toEqual([])
    expect(
      suggestionsAfterConnect({
        catalog: [bom],
        installs: [],
        beforeTypes: [],
        afterTypes: ['kicad'],
        blocked: new Set(['bom'])
      })
    ).toEqual([])
    expect(
      suggestionsAfterConnect({
        catalog: [bom],
        installs: [],
        beforeTypes: ['onshape'],
        afterTypes: ['onshape', 'kicad']
      })
    ).toEqual([])
  })

  it('is empty when nothing new connected', () => {
    expect(
      suggestionsAfterConnect({
        catalog: [bom],
        installs: [],
        beforeTypes: ['kicad'],
        afterTypes: ['kicad']
      })
    ).toEqual([])
  })
})

describe('suggestionToast', () => {
  it('names the widget, the prerequisite and how many more there are', () => {
    const [one, two] = suggestionsAfterConnect({
      catalog: [bom, experiments],
      installs: [],
      beforeTypes: [],
      afterTypes: ['kicad', 'ros']
    })
    expect(suggestionToast([one!, two!])).toEqual({
      title: 'BOM is now available',
      body: 'You connected an EDA tool. Bill of materials. 1 more widget is available too.',
      slug: 'bom'
    })
    expect(suggestionToast([])).toBeNull()
  })
})
