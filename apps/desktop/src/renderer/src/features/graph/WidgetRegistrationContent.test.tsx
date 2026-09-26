import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { Entity } from '../../lib/api/resources'
import { WidgetRegistrationContent } from './WidgetRegistrationContent'
const widget: Entity = {
  id: 'widget',
  name: 'Parts list',
  type: 'solus:widget',
  domain: 'workspace',
  origin: 'system',
  project_id: 'p1',
  source_key: null,
  properties: {
    slug: 'parts-list',
    enabled: true,
    blocked: false,
    version: '1.2',
    publisher: 'Team',
    views: ['page']
  }
}
it('shows registered metadata and opens its supported page', () => {
  const open = vi.fn()
  render(
    <WidgetRegistrationContent entity={widget} projectId="p1" mode="Guide" onOpenWidget={open} />
  )
  expect(screen.getByText(/1.2/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Open Parts list' }))
  expect(open).toHaveBeenCalledWith('parts-list')
})
it.each([
  { enabled: false, blocked: false },
  { enabled: true, blocked: true },
  { enabled: true, blocked: false, views: ['widget'] }
])('does not open disabled, blocked or page-less widgets: %j', (properties) => {
  const open = vi.fn()
  render(
    <WidgetRegistrationContent
      entity={{ ...widget, properties: { ...widget.properties, ...properties } }}
      projectId="p1"
      mode="Expert"
      onOpenWidget={open}
    />
  )
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(open).not.toHaveBeenCalled()
})
it('opens the persisted Live Bench through its existing callback', () => {
  const open = vi.fn()
  render(
    <WidgetRegistrationContent
      entity={{ ...widget, type: 'solus:live_bench', name: 'Live Bench' }}
      projectId="p1"
      mode="Guide"
      onOpenBench={open}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Open Live Bench' }))
  expect(open).toHaveBeenCalledOnce()
})
it('refuses foreign and connector-authored lookalikes', () => {
  const view = render(
    <WidgetRegistrationContent
      entity={{ ...widget, project_id: 'p2' }}
      projectId="p1"
      mode="Guide"
    />
  )
  expect(view.container).toBeEmptyDOMElement()
  view.rerender(
    <WidgetRegistrationContent
      entity={{ ...widget, origin: 'connector' }}
      projectId="p1"
      mode="Guide"
    />
  )
  expect(view.container).toBeEmptyDOMElement()
})
