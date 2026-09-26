import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { GraphNavigator } from './GraphNavigator'
import type { Entity } from '../../../lib/api/resources'
const entities: Entity[] = Array.from({ length: 4 }, (_, i) => ({
  id: String(i),
  name: `Node ${i}`,
  type: 'part',
  domain: 'mechanical',
  source_key: null
}))
const positions = {
  '0': { x: -700, y: 0 },
  '1': { x: 700, y: 0 },
  '2': { x: 0, y: -400 },
  '3': { x: 0, y: 400 }
}
afterEach(() => vi.restoreAllMocks())
it('fits a small saved overview in the available viewport without writing or changing world points', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  const onMove = vi.fn()
  const { container } = render(
    <GraphNavigator
      projectId="p"
      entities={entities}
      relations={[]}
      positions={positions}
      focusedId={null}
      onSelect={vi.fn()}
      onMove={onMove}
    />
  )
  const stage = container.querySelector<HTMLElement>('.graph-level')!
  const scale = Number(stage.style.getPropertyValue('zoom'))
  expect(scale).toBeGreaterThan(0)
  expect(scale).toBeLessThan(1)
  expect(1680 * scale).toBeLessThanOrEqual(800)
  expect(1050 * scale).toBeLessThanOrEqual(600)
  expect(screen.getByTestId('graph-node-0')).toHaveAttribute('data-x', '-700')
  expect(onMove).not.toHaveBeenCalled()
})
it('converts pointer movement on a fitted overview back into persisted world coordinates', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  const onMove = vi.fn()
  const { container } = render(
    <GraphNavigator
      projectId="p"
      entities={entities}
      relations={[]}
      positions={positions}
      focusedId={null}
      onSelect={vi.fn()}
      onMove={onMove}
    />
  )
  const scale = Number(
    container.querySelector<HTMLElement>('.graph-level')!.style.getPropertyValue('zoom')
  )
  const card = screen.getByTestId('graph-node-0')
  fireEvent.pointerDown(card, { pointerId: 1, button: 0, clientX: 100, clientY: 100 })
  fireEvent.pointerMove(card, { pointerId: 1, clientX: 150, clientY: 100 })
  fireEvent.pointerUp(card, { pointerId: 1, clientX: 150, clientY: 100 })
  expect(onMove).toHaveBeenCalledWith('0', { x: -700 + 50 / scale, y: 0 })
})

it('fits when an asynchronously loaded projection reduces a large level to a small overview', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  const props = {
    projectId: 'p',
    relations: [],
    positions,
    focusedId: null,
    onSelect: vi.fn(),
    onMove: vi.fn()
  }
  const extra = Array.from({ length: 3 }, (_, i) => ({ ...entities[0], id: `extra${i}` }))
  const view = render(<GraphNavigator {...props} entities={[...entities, ...extra]} />)
  const stage = view.container.querySelector<HTMLElement>('.graph-level')!
  expect(stage.style.getPropertyValue('zoom')).toBe('')
  view.rerender(<GraphNavigator {...props} entities={entities} />)
  expect(Number(stage.style.getPropertyValue('zoom'))).toBeGreaterThan(0)
  expect(Number(stage.style.getPropertyValue('zoom'))).toBeLessThan(1)
  expect(props.onMove).not.toHaveBeenCalled()
})

it('offers accessible Fit and 100% controls without modifying saved positions', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  const onMove = vi.fn()
  const props = {
    projectId: 'p',
    entities,
    relations: [],
    positions,
    focusedId: null,
    onSelect: vi.fn(),
    onMove
  }
  const view = render(<GraphNavigator {...props} />)
  const stage = view.container.querySelector<HTMLElement>('.graph-level')!
  const fitted = stage.style.getPropertyValue('zoom')
  fireEvent.click(screen.getByRole('button', { name: 'Show graph at 100%' }))
  expect(stage.style.getPropertyValue('zoom')).toBe('1')
  view.rerender(<GraphNavigator {...props} focusedId="0" />)
  expect(stage.style.getPropertyValue('zoom')).toBe('1')
  fireEvent.click(screen.getByRole('button', { name: 'Fit graph in view' }))
  expect(stage.style.getPropertyValue('zoom')).toBe(fitted)
  expect(screen.getByTestId('graph-node-0')).toHaveAttribute('data-x', '-700')
  expect(onMove).not.toHaveBeenCalled()
})
