import { expect, it } from 'vitest'
import type { Entity, Relation } from '../../lib/api/resources'
import { widgetRegistrationProjection } from './widgetRegistrationProjection'

const node = (id: string, type: string): Entity => ({
  id,
  name: id,
  type,
  domain: 'workspace',
  origin: 'system',
  project_id: 'p1',
  source_key: null
})
const root = node('workspace', 'solus:workspace')
const bench = node('bench', 'solus:live_bench')
const widget = node('widget', 'solus:widget')
const edge = (id: string): Relation => ({
  id: `edge-${id}`,
  type: 'contains',
  from_entity_id: root.id,
  to_entity_id: id
})
it('lifts persisted registrations with stable IDs and hides only their empty container', () => {
  const nodes = [root, bench, widget]
  const relations = [edge('bench'), edge('widget')]
  const result = widgetRegistrationProjection('p1', nodes, relations)
  expect(result.entities).toEqual([bench, widget])
  expect(result.relations).toEqual([])
  expect(nodes).toHaveLength(3)
  expect(relations).toHaveLength(2)
})
it('does not fabricate registrations and reflects uninstall on the next snapshot', () => {
  expect(widgetRegistrationProjection('p1', [], [])).toEqual({ entities: [], relations: [] })
  expect(widgetRegistrationProjection('p1', [root, bench], [edge('bench')]).entities).toEqual([
    bench
  ])
})
it('preserves non-registration children and rejects cross-project or non-system lookalikes', () => {
  const manual = { ...widget, id: 'manual', origin: 'manual' }
  const foreign = { ...widget, id: 'foreign', project_id: 'p2' }
  const nodes = [root, bench, manual, foreign]
  const result = widgetRegistrationProjection('p1', nodes, [
    edge('bench'),
    edge('manual'),
    edge('foreign')
  ])
  expect(result.entities).toEqual(nodes)
  expect(result.relations).toEqual([edge('manual'), edge('foreign')])
})
