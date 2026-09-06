import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { GraphNavigator, type GraphNavigatorProps } from './GraphNavigator'

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
})

describe('GraphNavigator', () => {
  it('enters three levels, scopes a leaf with its real path, and returns through breadcrumbs', () => {
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
    fireEvent.click(screen.getByRole('button', { name: 'Back to assembly' }))
    expect(depth()).toBe('2')
    expect(props.onSelect).toHaveBeenLastCalledWith(props.entities[1], [
      { entity: props.entities[0], relation: 'contains' }
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Project overview' }))
    expect(depth()).toBe('0')
    expect(card('root')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out one level' }))
    expect(container.querySelector('.graph-level')).toHaveAttribute('data-direction', 'out')
    rect.mockRestore()
  })

  it('exposes actual cross-link endpoints and navigates to an external endpoint', () => {
    const { props } = mount({
      entities: [node('root'), node('part'), node('controller')],
      relations: [edge('root', 'part'), edge('part', 'controller', 'connected_to')]
    })
    fireEvent.doubleClick(selectButton('root'))
    expect(screen.getByText('connected_to')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show linked controller' }))
    expect(depth()).toBe('0')
    expect(props.onSelect).toHaveBeenLastCalledWith(props.entities[2], [])
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
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
  })
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
