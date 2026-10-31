import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { useFocusStore } from '../../workspace/focusStore'
import { GraphNavigator, type GraphNavigatorProps } from './GraphNavigator'
import { layoutLevel } from './layout'

const node = (id: string, type = 'part'): Entity => ({
  id,
  type,
  name: id,
  domain: 'mechanical',
  source_key: id
})
const edge = (from: string, to: string, type = 'contains'): Relation => ({
  id: `${from}-${to}-${type}`,
  type,
  from_entity_id: from,
  to_entity_id: to
})
function mount(overrides: Partial<GraphNavigatorProps> = {}) {
  const props: GraphNavigatorProps = {
    projectId: 'p1',
    entities: ['root', 'assembly', 'part', 'leaf'].map((id) => node(id)),
    relations: [edge('root', 'assembly'), edge('assembly', 'part'), edge('part', 'leaf')],
    positions: {},
    focusedId: null,
    onMove: vi.fn(),
    onSelect: vi.fn(),
    ...overrides
  }
  return { props, ...render(<GraphNavigator {...props} />) }
}
const card = (id: string) => screen.getByTestId(`graph-node-${id}`)
const selectButton = (id: string) => within(card(id)).getByRole('button', { name: `Select ${id}` })
const depth = () => screen.getByTestId('graph-navigator').getAttribute('data-depth')
const rectangle = (x: number, y: number, width: number, height: number): DOMRect => ({
  x,
  y,
  width,
  height,
  left: x,
  top: y,
  right: x + width,
  bottom: y + height,
  toJSON: () => ({})
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  // Unmount BEFORE the reset: the navigator subscribes to the focus store's highlight, and this
  // hook runs ahead of testing-library's own cleanup, so a reset under a mounted navigator would
  // be a state update outside act().
  cleanup()
  useFocusStore.getState().reset()
})

describe('GraphNavigator', () => {
  registerHierarchyNavigationTests()

  registerBoundedRenderingTests()
})

describe('GraphNavigator anchor-relative packing', () => {
  const tree = {
    entities: [node('root'), node('a'), node('b')],
    relations: [edge('root', 'a'), edge('root', 'b')]
  }

  it('packs unsaved children around the entered card and keeps a saved child put', () => {
    mount({ ...tree, positions: { root: { x: 320, y: 60 }, b: { x: -20, y: 5 } } })
    fireEvent.doubleClick(selectButton('root'))
    expect(card('a')).toHaveAttribute('data-x', '320')
    expect(card('a')).toHaveAttribute('data-y', '60')
    expect(card('b')).toHaveAttribute('data-x', '-20')
    expect(card('b')).toHaveAttribute('data-y', '5')
    // No parent chip: containment is one stem from the frame's top edge with a drop per card.
    expect(screen.queryByRole('button', { name: /^Back to/ })).toBeNull()
    expect(document.querySelectorAll('.graph-structure-edge')).toHaveLength(2)
  })

  it('spirals the second unsaved child one step out from the entered card', () => {
    mount({ ...tree, positions: { root: { x: 320, y: 60 } } })
    fireEvent.doubleClick(selectButton('root'))
    expect(card('b')).toHaveAttribute(
      'data-x',
      String(layoutLevel(tree.entities.slice(1), {}, { x: 320, y: 60 }).b.x)
    )
    expect(card('b')).toHaveAttribute(
      'data-y',
      String(layoutLevel(tree.entities.slice(1), {}, { x: 320, y: 60 }).b.y)
    )
  })

  it('packs a revealed sibling level around its saved parent', () => {
    const { props, rerender } = mount({
      entities: [...tree.entities, node('other')],
      relations: [...tree.relations, edge('b', 'other', 'connected_to')],
      positions: { root: { x: 320, y: 60 } }
    })
    rerender(<GraphNavigator {...props} reveal={{ entityId: 'a', sequence: 1 }} />)
    expect(depth()).toBe('1')
    expect(card('a')).toHaveAttribute('data-x', '320')
    expect(card('a')).toHaveAttribute('data-y', '60')
  })
})

describe('GraphNavigator overlay', () => {
  it('renders the overlay at the viewport edge without affecting the level or its cards', () => {
    mount({ overlay: <div data-testid="rail">rail</div> })
    const rail = screen.getByTestId('rail')
    expect(rail.parentElement).toHaveClass('graph-overlay')
    expect(rail.closest('.graph-viewport-frame')).toContainElement(
      screen.getByTestId('graph-node-root')
    )
    expect(rail.closest('.graph-level')).toBeNull()
    expect(screen.getAllByTestId(/^graph-node-/)).toHaveLength(1)
    expect(depth()).toBe('0')
  })
})

describe('GraphNavigator interactions and isolation', () => {
  it('anchors an inward transition at the selected screen position and reverses outward motion', () => {
    const rect = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        if (this.dataset.testid === 'graph-node-root') return rectangle(140, 160, 224, 164)
        return rectangle(100, 100, 384, 324)
      })
    const { container } = mount()
    fireEvent.doubleClick(selectButton('root'))
    const stage = container.querySelector<HTMLElement>('.graph-level')!
    expect(stage.style.getPropertyValue('--graph-origin-x')).toBe('152px')
    expect(stage.style.getPropertyValue('--graph-origin-y')).toBe('142px')
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
    expect(container.querySelector('.graph-level')).toHaveAttribute('data-direction', 'out')
    rect.mockRestore()
  })

  it('draws a cross-link between sibling cards and lists nothing below the canvas', () => {
    mount({
      entities: [node('root'), node('part'), node('controller')],
      relations: [edge('root', 'part'), edge('part', 'controller', 'connected_to')]
    })
    // root and controller are both roots; the part→controller link projects onto root.
    expect(document.querySelectorAll('.graph-cross-edge')).toHaveLength(1)
    expect(screen.queryByText(/real endpoints/)).toBeNull()
    expect(document.querySelector('details')).toBeNull()
    fireEvent.doubleClick(selectButton('root'))
    // Inside root only `part` is visible; its link leaves the level and is not drawn.
    expect(document.querySelectorAll('.graph-cross-edge')).toHaveLength(0)
  })

  it('connects the level: the parent chip down to each card, and the .solus hub to the roots', () => {
    const roots = mount({
      entities: [node('solus', 'solus_config'), node('onshape'), node('kicad')],
      relations: []
    })
    expect(roots.container.querySelectorAll('.graph-structure-edge')).toHaveLength(2)
    roots.unmount()
    const nested = mount({
      entities: [node('root'), node('a'), node('b')],
      relations: [edge('root', 'a'), edge('root', 'b')]
    })
    fireEvent.doubleClick(selectButton('root'))
    expect(nested.container.querySelectorAll('.graph-structure-edge')).toHaveLength(2)
  })

  it('pans by dragging the canvas background, never from a card', () => {
    const { container } = mount()
    const viewport = container.querySelector<HTMLElement>('.graph-viewport')!
    viewport.scrollLeft = 200
    viewport.scrollTop = 100
    const level = container.querySelector<HTMLElement>('.graph-level')!
    fireEvent.pointerDown(level, { pointerId: 7, button: 0, clientX: 300, clientY: 300 })
    expect(viewport).toHaveAttribute('data-panning', 'true')
    fireEvent.pointerMove(level, { pointerId: 7, clientX: 250, clientY: 320 })
    expect(viewport.scrollLeft).toBe(250)
    expect(viewport.scrollTop).toBe(80)
    fireEvent.pointerUp(level, { pointerId: 7 })
    expect(viewport).not.toHaveAttribute('data-panning')
    fireEvent.pointerDown(card('root'), { pointerId: 8, button: 0, clientX: 0, clientY: 0 })
    expect(viewport).not.toHaveAttribute('data-panning')
  })

  it('shows paging only when a level overflows the card cap', () => {
    mount()
    expect(screen.queryByRole('button', { name: 'Next nodes' })).toBeNull()
  })
})

describe('GraphNavigator transition coordinates', () => {
  it.each([
    { name: 'scrolled', width: 1000, height: 600, left: 0, top: 0, x: 1232, y: 436 },
    { name: 'centered', width: 384, height: 324, left: 128, top: 48, x: 924, y: 298 }
  ])('anchors a scaled $name stage using its physical position', (layout) => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: HTMLElement
    ) {
      if (this.dataset.testid === 'graph-node-root') return rectangle(1042, 347, 224, 164)
      if (this.classList.contains('graph-viewport')) return rectangle(100, 80, 644, 426)
      // The entering animation scales the stage's rectangle about its previous origin.
      return rectangle(430, 126, layout.width * 0.38, layout.height * 0.38)
    })
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(640)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(420)
    vi.spyOn(HTMLElement.prototype, 'clientLeft', 'get').mockReturnValue(2)
    vi.spyOn(HTMLElement.prototype, 'clientTop', 'get').mockReturnValue(3)
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(layout.width)
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(layout.height)
    vi.spyOn(HTMLElement.prototype, 'offsetLeft', 'get').mockReturnValue(layout.left)
    vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockReturnValue(layout.top)
    const { container } = mount({ positions: { root: { x: 320, y: 60 } } })
    fireEvent.doubleClick(selectButton('root'))
    const stage = container.querySelector<HTMLElement>('.graph-level')!
    expect(stage.style.getPropertyValue('--graph-origin-x')).toBe(`${layout.x}px`)
    expect(stage.style.getPropertyValue('--graph-origin-y')).toBe(`${layout.y}px`)
  })
})

describe('GraphNavigator editing and project isolation', () => {
  registerPointerMovementTests()

  registerNavigationBoundariesTests()
})

it('reveals an externally chosen service root from another level exactly once', () => {
  const { props, rerender } = mount()
  fireEvent.doubleClick(selectButton('root'))
  expect(depth()).toBe('1')
  const selected = node('service-root', 'cad_document')
  const reveal = { entityId: selected.id, sequence: 1 }
  rerender(<GraphNavigator {...props} reveal={reveal} />)
  expect(depth()).toBe('1')
  rerender(<GraphNavigator {...props} entities={[...props.entities, selected]} reveal={reveal} />)
  expect(depth()).toBe('0')
  expect(selectButton('service-root')).toBeInTheDocument()
  expect(props.onSelect).toHaveBeenLastCalledWith(selected, [])
  const calls = vi.mocked(props.onSelect).mock.calls.length
  rerender(<GraphNavigator {...props} entities={[...props.entities, selected]} reveal={reveal} />)
  expect(props.onSelect).toHaveBeenCalledTimes(calls)
})

it('brings a revealed root into the viewport even when the overview level is unchanged', () => {
  const { props, rerender } = mount({
    entities: [node('root'), node('service-root')],
    relations: []
  })
  const viewport = screen
    .getByTestId('graph-navigator')
    .querySelector('.graph-viewport') as HTMLElement
  Object.defineProperties(viewport, { clientWidth: { value: 500 }, clientHeight: { value: 300 } })
  Object.defineProperties(card('service-root'), {
    offsetLeft: { value: 700 },
    offsetTop: { value: 500 },
    offsetWidth: { value: 224 },
    offsetHeight: { value: 164 }
  })
  rerender(<GraphNavigator {...props} reveal={{ entityId: 'service-root', sequence: 1 }} />)
  expect(viewport.scrollLeft).toBe(562)
  expect(viewport.scrollTop).toBe(432)
  expect(selectButton('service-root')).toHaveFocus()
})

// SOLUSDEV-250 P6: cards are memoised behind id-keyed stable handlers, so a
// parent re-render that changes nothing they show (a robot-session publish's
// busy flag) re-renders zero cards, and a focus change touches two.
describe('GraphNavigator render cost', () => {
  const probe = vi.fn((entity: Entity) => <span>{entity.id}</span>)
  function Harness({ focusedId = null }: { focusedId?: string | null }): React.JSX.Element {
    const [busy, setBusy] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setBusy(!busy)}>
          {busy ? 'busy' : 'idle'}
        </button>
        <GraphNavigator
          projectId="p1"
          entities={tree.entities}
          relations={tree.relations}
          positions={positions}
          focusedId={focusedId}
          onMove={onMove}
          onSelect={onSelect}
          renderContent={probe}
        />
      </>
    )
  }
  const tree = { entities: [node('a'), node('b'), node('c')], relations: [] as Relation[] }
  const positions = {}
  const onMove = vi.fn()
  const onSelect = vi.fn()

  it('re-renders zero cards when the parent publishes an unrelated state change', () => {
    probe.mockClear()
    render(<Harness />)
    expect(probe).toHaveBeenCalledTimes(3)
    fireEvent.click(screen.getByRole('button', { name: 'idle' }))
    expect(screen.getByRole('button', { name: 'busy' })).toBeInTheDocument()
    expect(probe).toHaveBeenCalledTimes(3)
  })

  it('re-renders only the two cards a focus change touches', () => {
    probe.mockClear()
    const { rerender } = render(<Harness focusedId="a" />)
    expect(probe).toHaveBeenCalledTimes(3)
    rerender(<Harness focusedId="b" />)
    expect(probe).toHaveBeenCalledTimes(5)
    expect(
      probe.mock.calls
        .slice(3)
        .map(([entity]) => entity.id)
        .sort()
    ).toEqual(['a', 'b'])
  })

  // SOLUSDEV-321 P1-T6: the navigator reads the focus store's highlight and hands each card a
  // boolean, so a glow starting or ending re-renders only the cards it touches.
  it('glows the cards SOL highlighted and re-renders only those', () => {
    probe.mockClear()
    render(<Harness />)
    expect(probe).toHaveBeenCalledTimes(3)
    act(() => useFocusStore.setState({ highlightedIds: ['b'] }))
    expect(screen.getByTestId('graph-node-b')).toHaveClass('graph-node-highlighted')
    expect(screen.getByTestId('graph-node-a')).not.toHaveClass('graph-node-highlighted')
    expect(probe).toHaveBeenCalledTimes(4)
    expect(probe.mock.calls[3][0].id).toBe('b')
    act(() => useFocusStore.getState().clearHighlight())
    expect(screen.getByTestId('graph-node-b')).not.toHaveClass('graph-node-highlighted')
    expect(probe).toHaveBeenCalledTimes(5)
  })
})

function registerHierarchyNavigationTests(): void {
  it('enters three levels, scopes a leaf with its real path, and returns through the parent chip and Help', () => {
    const { props } = mount()
    fireEvent.doubleClick(selectButton('root'))
    fireEvent.doubleClick(selectButton('assembly'))
    fireEvent.doubleClick(selectButton('part'))
    expect(depth()).toBe('3')
    fireEvent.click(selectButton('leaf'))
    expect(props.onSelect).toHaveBeenLastCalledWith(props.entities[3], [
      { entity: props.entities[0], relation: 'contains' },
      { entity: props.entities[1], relation: 'contains' },
      { entity: props.entities[2], relation: 'contains' }
    ])
    fireEvent.doubleClick(selectButton('leaf'))
    expect(depth()).toBe('3')
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
    expect(depth()).toBe('2')
    expect(props.onSelect).toHaveBeenLastCalledWith(props.entities[1], [
      { entity: props.entities[0], relation: 'contains' }
    ])
    expect(screen.queryByRole('button', { name: 'Project overview' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Help' }))
    expect(screen.getByRole('dialog', { name: 'Workspace help' })).toHaveTextContent(
      'Project › root › assembly'
    )
    fireEvent.click(screen.getByRole('button', { name: 'Project overview' }))
    expect(depth()).toBe('0')
    expect(card('root')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows Help top-right and closes it on Escape or an outside click without leaving the level', () => {
    mount()
    fireEvent.doubleClick(selectButton('root'))
    const help = screen.getByRole('button', { name: 'Help' })
    expect(help.closest('.graph-corner-right')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom out (Esc)' })).toBeInTheDocument()
    fireEvent.click(help)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(help)
    fireEvent.pointerDown(card('assembly'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(depth()).toBe('1')
  })

  it('supports hover-wheel one level at a time and keyboard navigation', () => {
    vi.useFakeTimers()
    mount()
    fireEvent.wheel(card('root'), { deltaY: -100 })
    expect(depth()).toBe('1')
    fireEvent.wheel(card('assembly'), { deltaY: -100 })
    expect(depth()).toBe('1')
    act(() => vi.advanceTimersByTime(400))
    fireEvent.wheel(card('assembly'), { deltaY: -100 })
    expect(depth()).toBe('2')
    fireEvent.keyDown(selectButton('part'), { key: 'ArrowRight' })
    expect(depth()).toBe('3')
    fireEvent.keyDown(selectButton('leaf'), { key: 'ArrowLeft' })
    expect(depth()).toBe('2')
    act(() => vi.advanceTimersByTime(400))
    fireEvent.wheel(screen.getByTestId('graph-navigator'), { deltaY: 100 })
    expect(depth()).toBe('1')
  })
}

function registerBoundedRenderingTests(): void {
  it('renders at most 24 cards and pages 243 children without mounting hidden nodes', () => {
    const children = Array.from({ length: 243 }, (_, i) =>
      node(`part-${String(i).padStart(3, '0')}`)
    )
    mount({
      entities: [node('root'), ...children],
      relations: children.map((e) => edge('root', e.id))
    })
    fireEvent.click(screen.getByRole('button', { name: 'Zoom into root' }))
    expect(screen.getAllByTestId(/^graph-node-/)).toHaveLength(24)
    expect(screen.queryByTestId('graph-node-part-024')).not.toBeInTheDocument()
    expect(screen.getByText('1–24 of 243')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next nodes' }))
    expect(screen.getAllByTestId(/^graph-node-/)).toHaveLength(24)
    expect(card('part-024')).toBeInTheDocument()
    expect(screen.queryByTestId('graph-node-part-000')).not.toBeInTheDocument()
  })
}

function registerPointerMovementTests(): void {
  it('moves nodes using pointer and keyboard world coordinates and preserves callbacks', () => {
    const { props } = mount({
      entities: [node('root')],
      relations: [],
      positions: { root: { x: 0, y: 0 } }
    })
    const handle = screen.getByRole('button', { name: 'Move root' })
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 10, clientY: 20, button: 0 })
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 110, clientY: 70 })
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 110, clientY: 70 })
    expect(props.onMove).toHaveBeenLastCalledWith('root', { x: 100, y: 50 })
    expect(card('root')).toHaveAttribute('data-x', '100')
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(props.onMove).toHaveBeenLastCalledWith('root', { x: 140, y: 50 })
  })

  it('drags from the card body past 4px without selecting, while a plain click still selects', () => {
    const { props } = mount({
      entities: [node('root')],
      relations: [],
      positions: { root: { x: 0, y: 0 } }
    })
    const body = selectButton('root')
    fireEvent.pointerDown(body, { pointerId: 2, clientX: 10, clientY: 20, button: 0 })
    fireEvent.pointerMove(body, { pointerId: 2, clientX: 12, clientY: 21 })
    expect(props.onMove).not.toHaveBeenCalled()
    fireEvent.pointerMove(body, { pointerId: 2, clientX: 110, clientY: 70 })
    expect(card('root')).toHaveClass('graph-node-dragging')
    fireEvent.pointerUp(body, { pointerId: 2, clientX: 110, clientY: 70 })
    fireEvent.click(body, { detail: 1 })
    expect(props.onMove).toHaveBeenLastCalledWith('root', { x: 100, y: 50 })
    expect(card('root')).toHaveAttribute('data-x', '100')
    expect(card('root')).not.toHaveClass('graph-node-dragging')
    expect(props.onSelect).not.toHaveBeenCalled()
    fireEvent.pointerDown(body, { pointerId: 3, clientX: 10, clientY: 20, button: 0 })
    fireEvent.pointerUp(body, { pointerId: 3, clientX: 11, clientY: 20 })
    fireEvent.click(body, { detail: 1 })
    expect(props.onSelect).toHaveBeenCalledTimes(1)
    expect(props.onMove).toHaveBeenCalledTimes(1)
  })

  it('a body drag released on the footer zoom button moves the node without entering it', () => {
    const { props } = mount({
      entities: [node('root'), node('child')],
      relations: [edge('root', 'child')],
      positions: { root: { x: 0, y: 0 } }
    })
    const footer = screen.getByRole('button', { name: 'Zoom into root' })
    fireEvent.pointerDown(footer, { pointerId: 4, clientX: 10, clientY: 20, button: 0 })
    fireEvent.pointerMove(footer, { pointerId: 4, clientX: 110, clientY: 70 })
    fireEvent.pointerUp(footer, { pointerId: 4, clientX: 110, clientY: 70 })
    fireEvent.click(footer, { detail: 1 })
    expect(props.onMove).toHaveBeenLastCalledWith('root', { x: 100, y: 50 })
    expect(depth()).toBe('0')
    expect(props.onSelect).not.toHaveBeenCalled()
  })
}

function registerNavigationBoundariesTests(): void {
  it('a keyboard activation after a drag still selects (detail 0 is never a drag click)', () => {
    const { props } = mount({
      entities: [node('root')],
      relations: [],
      positions: { root: { x: 0, y: 0 } }
    })
    const body = selectButton('root')
    fireEvent.pointerDown(body, { pointerId: 5, clientX: 10, clientY: 20, button: 0 })
    fireEvent.pointerMove(body, { pointerId: 5, clientX: 110, clientY: 70 })
    fireEvent.pointerUp(body, { pointerId: 5, clientX: 110, clientY: 70 })
    fireEvent.click(body, { detail: 0 })
    expect(props.onSelect).toHaveBeenCalledTimes(1)
  })

  it('resets navigation on project switch and excludes mismatched project entities', () => {
    const { props, rerender } = mount()
    fireEvent.doubleClick(selectButton('root'))
    rerender(
      <GraphNavigator
        {...props}
        projectId="p2"
        entities={[
          { ...node('new-root'), project_id: 'p2' },
          { ...node('foreign'), project_id: 'p1' }
        ]}
        relations={[]}
      />
    )
    expect(depth()).toBe('0')
    expect(card('new-root')).toBeInTheDocument()
    expect(screen.queryByTestId('graph-node-foreign')).not.toBeInTheDocument()
  })

  it('reuses context/content slots without interpreting embedded editor events as navigation', () => {
    const onContextMenu = vi.fn()
    mount({
      onContextMenu,
      renderContent: () => <textarea aria-label="Edit note" />,
      toolbar: <button>Add</button>
    })
    fireEvent.contextMenu(card('root'))
    expect(onContextMenu).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 'root' })
    )
    fireEvent.wheel(screen.getByRole('textbox'), { deltaY: -100 })
    expect(depth()).toBe('0')
    expect(screen.getByRole('button', { name: 'Add' }).parentElement).toHaveClass(
      'graph-corner-left'
    )
    expect(
      screen.getByRole('button', { name: 'Add' }).closest('.graph-viewport-frame')
    ).not.toBeNull()
  })
}

it('renders real immediate child previews with their real child counts', () => {
  mount()
  const root = card('root')
  expect(within(root).getByRole('button', { name: 'Open assembly' })).toBeInTheDocument()
  expect(within(root).getByText('1 inside — keep zooming')).toBeInTheDocument()
  expect(within(root).queryByRole('button', { name: 'Open part' })).toBeNull()
  fireEvent.click(within(root).getByRole('button', { name: 'Open assembly' }))
  expect(depth()).toBe('2')
})

it('persists missing defaults once and leaves saved points untouched on an import', () => {
  const entities = [node('a'), node('b')]
  const onMove = vi.fn()
  const { props, rerender } = mount({
    entities,
    relations: [],
    positions: { a: { x: 18, y: 32 } },
    persistDefaults: true,
    onMove
  })
  expect(onMove).toHaveBeenCalledTimes(1)
  expect(onMove.mock.calls[0][0]).toBe('b')
  // Default placement is labelled so a layout conflict on it is never shown as a user's loss.
  expect(onMove.mock.calls[0][2]).toBe('auto')
  const b = onMove.mock.calls[0][1] as { x: number; y: number }
  rerender(
    <GraphNavigator
      {...props}
      positions={{ a: { x: 18, y: 32 }, b }}
      entities={[...entities, node('c')]}
    />
  )
  expect(onMove).toHaveBeenCalledTimes(2)
  expect(onMove.mock.calls[1][0]).toBe('c')
  expect(card('a')).toHaveAttribute('data-x', '18')
  expect(card('b')).toHaveAttribute('data-x', String(b.x))
})

it('previews actual scoped robot roots without inventing an inside count', () => {
  const robot = node('robot', 'physical_robot')
  const first = node('brain-one', 'hardware_brain')
  const second = node('brain-two', 'hardware_brain')
  mount({
    entities: [robot],
    relations: [],
    scopeRootIds: ['robot'],
    scopeGraph: (rootId) =>
      rootId
        ? {
            entities: [robot, first, second],
            relations: [edge('robot', first.id), edge('robot', second.id)]
          }
        : { entities: [robot], relations: [] }
  })
  expect(within(card('robot')).getByRole('button', { name: 'Open brain-one' })).toBeInTheDocument()
  expect(within(card('robot')).getByRole('button', { name: 'Zoom into robot' })).toHaveTextContent(
    '2 nodes'
  )
  fireEvent.click(within(card('robot')).getByRole('button', { name: 'Open brain-one' }))
  expect(card('brain-one')).toBeInTheDocument()
  expect(depth()).toBe('1')
})

// SOLUSDEV-320 P4 — edge selection threads through the navigator, and the
// viewport context menu offers Re-layout for the current level.
describe('GraphNavigator edges and re-layout', () => {
  const pair = {
    entities: [node('a'), node('b')],
    relations: [edge('a', 'b', 'wires')],
    positions: { a: { x: 100, y: 100 }, b: { x: 400, y: 100 } }
  }

  it('clicking a drawn edge reports the relation and the selected one is marked', () => {
    const onSelectEdge = vi.fn()
    const { container, rerender, props } = mount({ ...pair, onSelectEdge })
    fireEvent.click(container.querySelector('.graph-cross-edge')!)
    expect(onSelectEdge).toHaveBeenCalledWith(pair.relations[0])
    expect(container.querySelector('g[data-selected]')).toBeNull()
    rerender(<GraphNavigator {...props} selectedEdgeId="a-b-wires" />)
    expect(container.querySelector('g[data-selected]')).not.toBeNull()
  })

  it('threads the findings map to each visible card', () => {
    const findings = new Map([['a', { severity: 'warning' as const, count: 2 }]])
    mount({ ...pair, findings })
    expect(within(card('a')).getByTitle('2 open findings, worst: warning')).toHaveTextContent('2')
    expect(card('b').querySelector('.graph-finding-badge')).toBeNull()
  })

  it('offers Re-layout on the viewport background and reports the level ids', () => {
    const onRelayout = vi.fn()
    mount({ ...pair, onRelayout })
    fireEvent.contextMenu(screen.getByTestId('graph-navigator').querySelector('.graph-viewport')!)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-layout' }))
    expect(onRelayout).toHaveBeenCalledWith(['a', 'b'])
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('leaves a card right-click alone and shows no menu without the prop', () => {
    const onRelayout = vi.fn()
    mount({ ...pair, onRelayout })
    fireEvent.contextMenu(card('a'))
    expect(screen.queryByRole('menuitem', { name: 'Re-layout' })).toBeNull()
    mount(pair)
    fireEvent.contextMenu(
      screen.getAllByTestId('graph-navigator')[1].querySelector('.graph-viewport')!
    )
    expect(screen.queryByRole('menuitem', { name: 'Re-layout' })).toBeNull()
  })

  it('re-sends default placement for cleared positions after Re-layout', () => {
    const onMove = vi.fn()
    const onRelayout = vi.fn()
    const { props, rerender } = mount({
      entities: pair.entities,
      relations: [],
      positions: {},
      persistDefaults: true,
      onMove,
      onRelayout
    })
    expect(onMove).toHaveBeenCalledTimes(2)
    const saved = { a: onMove.mock.calls[0][1], b: onMove.mock.calls[1][1] }
    rerender(<GraphNavigator {...props} positions={saved} />)
    rerender(<GraphNavigator {...props} positions={{}} />)
    expect(onMove).toHaveBeenCalledTimes(2)
    fireEvent.contextMenu(screen.getByTestId('graph-navigator').querySelector('.graph-viewport')!)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-layout' }))
    rerender(<GraphNavigator {...props} positions={saved} />)
    rerender(<GraphNavigator {...props} positions={{}} />)
    expect(onMove).toHaveBeenCalledTimes(4)
    expect(onMove.mock.calls[3][2]).toBe('auto')
  })
})

describe('GraphNavigator Escape and breadcrumb', () => {
  it('Escape goes up a level unless the owner consumes it, an editor has focus, or a dialog took it', () => {
    const onEscape = vi.fn(() => false)
    mount({ onEscape, renderContent: () => <textarea aria-label="Edit note" /> })
    fireEvent.doubleClick(selectButton('root'))
    fireEvent.doubleClick(selectButton('assembly'))
    expect(depth()).toBe('2')
    fireEvent.keyDown(screen.getAllByRole('textbox')[0], { key: 'Escape' })
    expect(depth()).toBe('2')
    const taken = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true, bubbles: true })
    taken.preventDefault()
    act(() => {
      window.dispatchEvent(taken)
    })
    expect(depth()).toBe('2')
    onEscape.mockReturnValueOnce(true)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onEscape).toHaveBeenCalledTimes(1)
    expect(depth()).toBe('2')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(depth()).toBe('1')
  })

  it('shows the trail as a breadcrumb with the level stat and navigates from it', () => {
    mount()
    expect(screen.getByText('1 ROOTS · 4 NODES · DOUBLE-CLICK TO ZOOM IN')).toBeInTheDocument()
    fireEvent.doubleClick(selectButton('root'))
    fireEvent.doubleClick(selectButton('assembly'))
    const trail = screen.getByRole('navigation', { name: 'Graph trail' })
    expect(trail).toHaveTextContent('Graph›root›assembly')
    expect(screen.getByText('1 NODES INSIDE · ESC TO ZOOM OUT')).toBeInTheDocument()
    fireEvent.click(within(trail).getByRole('button', { name: 'root' }))
    expect(depth()).toBe('1')
    fireEvent.click(within(trail).getByRole('button', { name: 'Zoom out (Esc)' }))
    expect(depth()).toBe('0')
  })
})
