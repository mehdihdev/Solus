// SOLUSDEV-321 P0-T3: what the SOL PAGE adds to a send beyond the typed text — where the
// person is looking (the workspace focus) and what they pinned — each in a field of its own.
import { beforeEach, describe, expect, it } from 'vitest'
import { MAX_FOCUS_PATH, type FocusStep } from '@solus/shared-types'
import { useFocusStore } from '../workspace/focusStore'
import { MAX_MENTIONS } from './mentionToken'
import { pageAnchors } from './pageAnchors'

/** A canonical UUID from a number: the server parses every anchor id as one. */
const id = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const ids = (count: number): string[] => Array.from({ length: count }, (_, n) => id(n + 1))

const step = (entityId: string): FocusStep => ({
  entity: { projectId: 'p1', entityId },
  domain: 'mechanical',
  relation: 'mounts'
})

beforeEach(() => {
  useFocusStore.getState().reset()
})

describe('pageAnchors', () => {
  it('says nothing when there is no focus and nothing is pinned', () => {
    expect(pageAnchors([])).toEqual({})
  })

  it('carries the focused entity with the trail it was reached through, oldest first', () => {
    useFocusStore.setState({ focusedEntityId: id(1), path: [step(id(2)), step(id(3))] })
    expect(pageAnchors([])).toEqual({ focus: { entityId: id(1), path: [id(2), id(3)] } })
  })

  it('a focus reached directly has an empty trail, and is still a focus', () => {
    useFocusStore.setState({ focusedEntityId: id(1), path: [] })
    expect(pageAnchors([])).toEqual({ focus: { entityId: id(1), path: [] } })
  })

  it('carries the pins beside the focus, never inside it', () => {
    useFocusStore.setState({ focusedEntityId: id(1), path: [] })
    expect(pageAnchors([id(5), id(6)])).toEqual({
      focus: { entityId: id(1), path: [] },
      pins: [id(5), id(6)]
    })
  })

  it('keeps only as many pins as the server accepts instead of 422ing the send', () => {
    const many = ids(MAX_MENTIONS + 2)
    expect(pageAnchors(many).pins).toEqual(many.slice(0, MAX_MENTIONS))
  })

  it('keeps the nearest steps of a trail longer than the server accepts', () => {
    const trail = ids(MAX_FOCUS_PATH + 4)
    useFocusStore.setState({ focusedEntityId: id(99), path: trail.map(step) })
    expect(pageAnchors([]).focus?.path).toEqual(trail.slice(-MAX_FOCUS_PATH))
  })
})

// The server parses every anchor id as a UUID and refuses the WHOLE turn (422) on one that is
// not. Nothing guarantees the focus is one: the store sets it before its neighbourhood loads
// and keeps it when the load fails, an extension's `focus.propose` takes any string, and a
// `[entity:…]` citation names whatever the model wrote. Such an id is dropped, never sent.
describe('pageAnchors — ids the server would refuse', () => {
  it('sends no focus at all when the focused id is not a UUID, but still sends the pins', () => {
    useFocusStore.setState({ focusedEntityId: 'entity:imu', path: [step(id(2))] })
    expect(pageAnchors([id(5)])).toEqual({ pins: [id(5)] })
  })

  it('drops a trail step that is not a UUID and keeps the rest, in order', () => {
    useFocusStore.setState({
      focusedEntityId: id(1),
      path: [step(id(2)), step('not-a-uuid'), step(id(3))]
    })
    expect(pageAnchors([])).toEqual({ focus: { entityId: id(1), path: [id(2), id(3)] } })
  })

  it('a dropped trail step does not use up one of the sixteen the server accepts', () => {
    const trail = ids(MAX_FOCUS_PATH)
    const withJunk = [...trail.slice(0, 8), 'not-a-uuid', ...trail.slice(8)]
    useFocusStore.setState({ focusedEntityId: id(99), path: withJunk.map(step) })
    expect(pageAnchors([]).focus?.path).toEqual(trail)
  })

  it('drops a pin that is not a UUID, and it does not use up one of the eight', () => {
    const good = ids(MAX_MENTIONS + 1)
    expect(pageAnchors(['legacy-pin', ...good]).pins).toEqual(good.slice(0, MAX_MENTIONS))
  })

  it('sends no pins at all when none of them is a UUID', () => {
    expect(pageAnchors(['legacy-pin', 'e1'])).toEqual({})
  })

  it('accepts a UUID in either case', () => {
    const shout = 'ABCDEF00-0000-4000-8000-000000000001'
    useFocusStore.setState({ focusedEntityId: shout, path: [] })
    expect(pageAnchors([shout]).focus).toEqual({ entityId: shout, path: [] })
    expect(pageAnchors([shout]).pins).toEqual([shout])
  })
})
