// SOLUSDEV-235 / EXT-15 — the pure layout table: ref parsing, the grid mapping,
// pruning, dedupe + cap, min-size gating, and the four edits.
import { describe, it, expect } from 'vitest'
import {
  DEFAULT_WIDGET_REF,
  MAX_SLOTS,
  SLOT_SIZES,
  addSlot,
  allowedSizes,
  builtinRef,
  defaultLayout,
  extRef,
  formatWidgetRef,
  isSizeAllowed,
  moveSlot,
  parseWidgetRef,
  pruneLayout,
  removeSlot,
  resizeSlot,
  slotSpan,
  type WidgetLayout
} from './layout'

const L: WidgetLayout = [
  { ref: 'builtin:livebench', size: 'wide' },
  { ref: 'ext:bom', size: 'standard' },
  { ref: 'builtin:reference', size: 'compact' }
]

describe('WidgetRef parse/format', () => {
  it.each([
    ['builtin:livebench', { kind: 'builtin', id: 'livebench' }],
    ['builtin:a', { kind: 'builtin', id: 'a' }],
    ['ext:bom', { kind: 'ext', slug: 'bom' }],
    ['ext:scope-viewer2', { kind: 'ext', slug: 'scope-viewer2' }]
  ])('parses %s', (text, expected) => {
    expect(parseWidgetRef(text)).toEqual(expected)
  })

  it.each([
    'livebench',
    'dev:bom',
    'builtin:',
    'builtin:Live',
    'builtin:1abc',
    'ext:b', // ext slugs are 2..64 chars
    `ext:${'a'.repeat(65)}`,
    `builtin:${'a'.repeat(65)}`,
    'ext:bom/../x',
    ''
  ])('rejects %j', (text) => {
    expect(parseWidgetRef(text)).toBeNull()
  })

  it('round-trips through format', () => {
    for (const text of ['builtin:livebench', 'ext:bom']) {
      const parsed = parseWidgetRef(text)
      expect(parsed).not.toBeNull()
      expect(formatWidgetRef(parsed!)).toBe(text)
    }
    expect(builtinRef('impact')).toBe('builtin:impact')
    expect(extRef('bom')).toBe('ext:bom')
  })
})

describe('defaultLayout', () => {
  it('is exactly one Live Bench slot at its preferred (wide) size', () => {
    expect(DEFAULT_WIDGET_REF).toBe('builtin:livebench')
    expect(defaultLayout()).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
  })
  it('returns a fresh array each call (callers may not share one)', () => {
    expect(defaultLayout()).not.toBe(defaultLayout())
  })
})

describe('slotSpan', () => {
  it.each([
    ['compact', 1],
    ['standard', 2],
    ['wide', 3],
    ['full', 4]
  ] as const)('%s spans %i of 4 columns', (size, span) => {
    expect(slotSpan(size)).toBe(span)
  })
  it('covers every slot size', () => {
    expect(SLOT_SIZES).toEqual(['compact', 'standard', 'wide', 'full'])
  })
})

describe('pruneLayout', () => {
  const available = { builtin: new Set(['livebench', 'reference']), ext: new Set(['bom']) }

  it('keeps a fully-known layout untouched', () => {
    expect(pruneLayout(L, available)).toEqual({ layout: L, dropped: [] })
  })

  it('drops unknown built-ins and unknown extensions, reporting each once', () => {
    const stored: WidgetLayout = [
      ...L,
      { ref: 'builtin:gone', size: 'compact' },
      { ref: 'ext:uninstalled', size: 'wide' }
    ]
    const result = pruneLayout(stored, available)
    expect(result.layout).toEqual(L)
    expect(result.dropped).toEqual(['builtin:gone', 'ext:uninstalled'])
  })

  it('drops malformed refs and duplicate refs (first wins)', () => {
    const stored: WidgetLayout = [
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'dev:bom', size: 'wide' },
      { ref: 'builtin:livebench', size: 'compact' }
    ]
    const result = pruneLayout(stored, available)
    expect(result.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
    expect(result.dropped).toEqual(['dev:bom', 'builtin:livebench'])
  })

  it('keeps every extension ref while the install snapshot is unknown (ext: null)', () => {
    const stored: WidgetLayout = [
      { ref: 'ext:mystery', size: 'standard' },
      { ref: 'builtin:gone', size: 'compact' }
    ]
    const result = pruneLayout(stored, { builtin: available.builtin, ext: null })
    expect(result.layout).toEqual([{ ref: 'ext:mystery', size: 'standard' }])
    expect(result.dropped).toEqual(['builtin:gone'])
  })
})

describe('addSlot', () => {
  it('appends at the requested size', () => {
    expect(addSlot(L, 'ext:scope', 'full')).toEqual([...L, { ref: 'ext:scope', size: 'full' }])
  })
  it('is a no-op for a ref already on the canvas (one slot per ref)', () => {
    expect(addSlot(L, 'ext:bom', 'full')).toBe(L)
  })
  it('refuses a malformed ref', () => {
    expect(addSlot(L, 'dev:bom', 'full')).toBe(L)
  })
  it(`refuses beyond ${MAX_SLOTS} slots`, () => {
    const full: WidgetLayout = Array.from({ length: MAX_SLOTS }, (_, i) => ({
      ref: `ext:w${i}x`,
      size: 'compact' as const
    }))
    expect(full).toHaveLength(24)
    expect(addSlot(full, 'ext:one-more', 'compact')).toBe(full)
    expect(addSlot(full.slice(0, MAX_SLOTS - 1), 'ext:one-more', 'compact')).toHaveLength(
      MAX_SLOTS
    )
  })
})

describe('removeSlot / resizeSlot / moveSlot', () => {
  it('removes by ref and leaves the rest in order', () => {
    expect(removeSlot(L, 'ext:bom')).toEqual([L[0], L[2]])
    expect(removeSlot(L, 'ext:nope')).toBe(L)
  })
  it('resizes one slot without touching the others', () => {
    expect(resizeSlot(L, 'ext:bom', 'full')).toEqual([L[0], { ref: 'ext:bom', size: 'full' }, L[2]])
    expect(resizeSlot(L, 'ext:bom', 'standard')).toBe(L)
    expect(resizeSlot(L, 'ext:nope', 'full')).toBe(L)
  })
  it('moves left and right, clamping at the ends', () => {
    expect(moveSlot(L, 'ext:bom', -1)).toEqual([L[1], L[0], L[2]])
    expect(moveSlot(L, 'ext:bom', 1)).toEqual([L[0], L[2], L[1]])
    expect(moveSlot(L, 'builtin:livebench', -1)).toBe(L)
    expect(moveSlot(L, 'builtin:reference', 1)).toBe(L)
    expect(moveSlot(L, 'ext:nope', 1)).toBe(L)
  })
  it('never mutates its input', () => {
    const before = JSON.stringify(L)
    addSlot(L, 'ext:x1', 'compact')
    removeSlot(L, 'ext:bom')
    resizeSlot(L, 'ext:bom', 'full')
    moveSlot(L, 'ext:bom', 1)
    pruneLayout(L, { builtin: new Set(), ext: new Set() })
    expect(JSON.stringify(L)).toBe(before)
  })
})

describe('min-size gating', () => {
  it('allows every size at or above the minimum', () => {
    expect(allowedSizes({ preferred: 'wide', minimum: 'standard' })).toEqual([
      'standard',
      'wide',
      'full'
    ])
    expect(isSizeAllowed('compact', { preferred: 'wide', minimum: 'standard' })).toBe(false)
    expect(isSizeAllowed('standard', { preferred: 'wide', minimum: 'standard' })).toBe(true)
  })
  it('allows everything without a minimum, and everything for an unknown widget', () => {
    expect(allowedSizes({ preferred: 'compact' })).toEqual(SLOT_SIZES)
    expect(allowedSizes(undefined)).toEqual(SLOT_SIZES)
  })
  it('pins a non-resizable widget to its preferred size', () => {
    expect(allowedSizes({ preferred: 'standard', resizable: false })).toEqual(['standard'])
  })
})
