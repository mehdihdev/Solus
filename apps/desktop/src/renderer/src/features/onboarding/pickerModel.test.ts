// The picker's pure rules: what a search shows, the order rows appear in, and
// what an edit changes. No DOM — the component only renders these answers.
import { describe, it, expect } from 'vitest'
import type { SelectableItem } from '../../lib/api/resources'
import {
  confirmLabel,
  matches,
  orderItems,
  selectionDiff,
  toggled,
  toggledAll
} from './pickerModel'

const A: SelectableItem = {
  id: 'a',
  name: 'SO101 Assembly.step',
  modified_at: '2026-10-01T00:00:00Z'
}
const B: SelectableItem = { id: 'b', name: 'Base_SO101.step', modified_at: '2026-10-20T00:00:00Z' }
const C: SelectableItem = { id: 'c', name: 'Elegoo Robot' }

describe('matches', () => {
  it('keeps everything for a blank query', () => {
    expect(matches([A, B, C], '  ')).toEqual([A, B, C])
  })

  it('matches case-insensitively anywhere in the name', () => {
    expect(matches([A, B, C], 'so101')).toEqual([A, B])
  })
})

describe('orderItems', () => {
  it('puts the most recently edited first, undated items last in listing order', () => {
    expect(orderItems([C, A, B])).toEqual([B, A, C])
  })

  it('keeps the listing order when nothing carries a date', () => {
    const plain = [
      { id: 'x', name: 'X' },
      { id: 'y', name: 'Y' }
    ]
    expect(orderItems(plain)).toEqual(plain)
  })
})

describe('toggled / toggledAll', () => {
  it('adds an unchosen id and removes a chosen one', () => {
    expect(toggled(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggled(['a', 'b'], 'a')).toEqual(['b'])
  })

  it('selects every shown id, keeping choices outside the view', () => {
    expect(toggledAll(['z'], ['a', 'b'])).toEqual(['z', 'a', 'b'])
  })

  it('clears only the shown ids when all of them are already chosen', () => {
    expect(toggledAll(['z', 'a', 'b'], ['a', 'b'])).toEqual(['z'])
  })
})

describe('selectionDiff', () => {
  it('reports what an edit adds and removes', () => {
    expect(selectionDiff(['a', 'b'], ['b', 'c'])).toEqual({ added: ['c'], removed: ['a'] })
  })

  it('is empty when nothing changed, whatever the order', () => {
    expect(selectionDiff(['a', 'b'], ['b', 'a'])).toEqual({ added: [], removed: [] })
  })
})

describe('confirmLabel', () => {
  it('counts with the connector noun', () => {
    expect(confirmLabel(1, 'document')).toBe('Track 1 document')
    expect(confirmLabel(3, 'document')).toBe('Track 3 documents')
  })

  it('names the action without a count when nothing is chosen', () => {
    expect(confirmLabel(0, 'repository')).toBe('Track repositories')
  })
})
