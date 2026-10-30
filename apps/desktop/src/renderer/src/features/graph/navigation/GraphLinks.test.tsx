// SOLUSDEV-250 P5 — the level draws cross-links between world points; containment arrives as
// `structure` lines (orthogonal, optionally sharing one bus Y) and there is no parent chip.
// SOLUSDEV-320 P4-T1 — edges with meaning: dominant-type labels, relation
// class/candidate attributes, bundle expansion, selection and hover sentences.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { buildNavigationIndex } from './graphIndex'
import { GraphLinkDrawing } from './GraphLinks'

const relation: Relation = {
  id: 'a-b',
  type: 'connected_to',
  from_entity_id: 'a',
  to_entity_id: 'b'
}
const points = { a: { x: 320, y: 60 }, b: { x: 620, y: 60 } }
const offset = { x: -100, y: -200 }
const entity = (id: string, name = id, domain = 'electrical'): Entity => ({
  id,
  name,
  type: 'part',
  domain,
  source_key: id
})
const drawing = (
  links: Relation[],
  extra: Partial<Parameters<typeof GraphLinkDrawing>[0]> = {}
): ReturnType<typeof render> =>
  render(
    <GraphLinkDrawing
      links={links.map((edge) => ({
        relation: edge,
        from: edge.from_entity_id,
        to: edge.to_entity_id
      }))}
      points={points}
      offset={offset}
      {...extra}
    />
  )
const paths = (container: HTMLElement): Element[] => [
  ...container.querySelectorAll('.graph-cross-edge')
]
const edge = (id: string, type: string, extra: Partial<Relation> = {}): Relation => ({
  ...relation,
  id,
  type,
  ...extra
})

describe('GraphLinkDrawing', () => {
  it('draws no containment path by default and keeps cross-links between world points', () => {
    const { container } = drawing([relation])
    expect(container.querySelector('.graph-structure-edge')).toBeNull()
    expect(container.querySelectorAll('.graph-cross-edge')).toHaveLength(1)
    expect(container.querySelector('.graph-cross-edge')).toHaveAttribute(
      'd',
      expect.stringContaining(' C ')
    )
    expect(screen.queryByRole('button', { name: /^Back to/ })).toBeNull()
  })

  it('draws structure lines orthogonally, across halfway or at the shared bus Y', () => {
    const { container } = drawing([], {
      structure: [
        { from: { x: 0, y: 0 }, to: { x: 320, y: 100 } },
        { from: { x: 0, y: 0 }, to: { x: 620, y: 100 }, via: 40 }
      ]
    })
    const d = [...container.querySelectorAll('.graph-structure-edge')].map((path) =>
      path.getAttribute('d')
    )
    expect(d).toEqual(['M 100 200 V 250 H 420 V 300', 'M 100 200 V 240 H 720 V 300'])
  })
})

describe('GraphLinkDrawing labels', () => {
  it('labels a bundle by its dominant type with a count, counting distinct relations only', () => {
    drawing([
      edge('one', 'connected_to'),
      edge('two', 'connected_to'),
      edge('three', 'reads_from'),
      edge('one', 'connected_to')
    ])
    expect(screen.getByText('connected to ×3')).toBeInTheDocument()
    expect(screen.queryByText(/links/)).toBeNull()
  })

  it('breaks a tie alphabetically and labels a single link by its bare type', () => {
    drawing([edge('one', 'reads_from'), edge('two', 'commands')])
    expect(screen.getByText('commands ×2')).toBeInTheDocument()
    drawing([edge('solo', 'wires')])
    expect(screen.getByText('wires')).toBeInTheDocument()
  })
})

describe('GraphLinkDrawing relation classes', () => {
  it.each([
    ['contains', 'structure'],
    ['wires', 'dependency'],
    ['same_as', 'identity'],
    ['verified_by', 'outcome'],
    ['connected_to', 'legacy'],
    ['made_up', 'legacy']
  ])('%s draws as class %s', (type, relationClass) => {
    const { container } = drawing([edge('r', type)])
    expect(container.querySelector('g[data-relation-class]')).toHaveAttribute(
      'data-relation-class',
      relationClass
    )
  })

  it('uses the dominant type for the bundle class', () => {
    const { container } = drawing([edge('a1', 'wires'), edge('a2', 'wires'), edge('b', 'same_as')])
    expect(container.querySelector('g[data-relation-class]')).toHaveAttribute(
      'data-relation-class',
      'dependency'
    )
  })

  it('marks a bundle as candidate only when every relation in it is one', () => {
    const candidate = { origin: 'inferred', confidence: 0.5 }
    const { container, unmount } = drawing([
      edge('c1', 'commands', candidate),
      edge('c2', 'reads', candidate)
    ])
    expect(container.querySelector('g[data-candidate]')).not.toBeNull()
    unmount()
    const mixed = drawing([
      edge('c1', 'commands', candidate),
      edge('f', 'reads', { origin: 'connector' })
    ])
    expect(mixed.container.querySelector('g[data-candidate]')).toBeNull()
    expect(mixed.container.querySelector('g[data-relation-class]')).not.toBeNull()
  })

  it('keeps the cross-domain accent when the endpoints live in different domains', () => {
    const index = buildNavigationIndex(
      [entity('a', 'a', 'code'), entity('b', 'b', 'electrical')],
      []
    )
    const { container } = drawing([edge('x', 'commands')], { index })
    expect(container.querySelector('.graph-cross-domain-edge')).not.toBeNull()
  })
})

describe('GraphLinkDrawing selection', () => {
  it('expands a bundle on click into one labelled path per relation, then selects one', () => {
    const onSelectEdge = vi.fn()
    const { container } = drawing([edge('one', 'wires'), edge('two', 'powers')], { onSelectEdge })
    expect(paths(container)).toHaveLength(1)
    fireEvent.click(paths(container)[0])
    expect(onSelectEdge).not.toHaveBeenCalled()
    expect(paths(container)).toHaveLength(2)
    expect(screen.getByText('wires')).toBeInTheDocument()
    expect(screen.getByText('powers')).toBeInTheDocument()
    expect(screen.queryByText(/×/)).toBeNull()
    expect(container.querySelectorAll('g[data-relation-class="dependency"]')).toHaveLength(2)
    fireEvent.click(paths(container)[1])
    expect(onSelectEdge).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'two', type: 'powers' })
    )
  })

  it('selects a single-relation path directly and marks the selected one', () => {
    const onSelectEdge = vi.fn()
    const { container } = drawing([edge('solo', 'wires')], { onSelectEdge, selectedEdgeId: 'solo' })
    fireEvent.click(paths(container)[0])
    expect(onSelectEdge).toHaveBeenCalledWith(expect.objectContaining({ id: 'solo' }))
    expect(container.querySelector('g[data-selected]')).not.toBeNull()
  })

  it('selects a path from the keyboard with Enter or Space', () => {
    const onSelectEdge = vi.fn()
    const { container } = drawing([edge('solo', 'wires')], { onSelectEdge })
    const path = paths(container)[0]
    expect(path.getAttribute('tabindex')).toBe('0')
    expect(path.getAttribute('role')).toBe('button')
    fireEvent.keyDown(path, { key: 'Enter' })
    fireEvent.keyDown(path, { key: ' ' })
    fireEvent.keyDown(path, { key: 'a' })
    expect(onSelectEdge).toHaveBeenCalledTimes(2)
  })

  it('never selects a synthetic projection relation', () => {
    const onSelectEdge = vi.fn()
    const { container } = drawing(
      [
        edge('topology-root:r1:n1', 'contains'),
        edge('account:c1:e1', 'contains', { to_entity_id: 'a' })
      ],
      { onSelectEdge }
    )
    for (const path of paths(container)) fireEvent.click(path)
    expect(onSelectEdge).not.toHaveBeenCalled()
  })

  it('titles every path with the hover sentence built from names and evidence', () => {
    const index = buildNavigationIndex([entity('a', 'firmware.ino:42'), entity('b', 'Motor-3')], [])
    const { container } = drawing(
      [
        edge('one', 'commands', {
          properties: { evidence: [{ kind: 'firmware_symbol', ref: 'firmware.ino:42' }] }
        })
      ],
      { index }
    )
    expect(container.querySelector('.graph-cross-edge title')?.textContent).toBe(
      'firmware.ino:42 commands Motor-3 (firmware symbol firmware.ino:42)'
    )
  })
})
