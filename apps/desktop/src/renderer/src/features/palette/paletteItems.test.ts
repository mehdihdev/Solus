import { describe, expect, it } from 'vitest'
import type { Entity, Project, TeamSummary } from '../../lib/api/resources'
import { nodeItems, pageItems, projectItems, teamItems } from './paletteItems'

const team = (team_id: string, name: string): TeamSummary => ({
  team_id,
  name,
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
})
const project = (id: string, team_id: string, name: string): Project => ({
  id,
  team_id,
  name,
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: ''
})
const entity = (id: string, name: string, over: Partial<Entity> = {}): Entity => ({
  id,
  name,
  type: 'ic',
  domain: 'ee',
  source_key: null,
  ...over
})

describe('pageItems', () => {
  it('lists every main screen as a page', () => {
    const labels = pageItems([]).map((item) => item.label)
    expect(labels).toEqual([
      'Home',
      'Workspace',
      'Live Bench',
      'SOL',
      'Store',
      'Billing',
      'Settings'
    ])
  })

  it('appends installed extension pages after the screens', () => {
    const items = pageItems([{ slug: 'bom', label: 'BOM' }])
    expect(items.at(-1)).toMatchObject({
      key: 'ext:bom',
      kind: 'page',
      label: 'BOM',
      target: { type: 'extension', slug: 'bom' }
    })
  })

  it('gives each screen a stable key and a screen target', () => {
    expect(pageItems([])[2]).toMatchObject({
      key: 'page:bench',
      target: { type: 'screen', screen: 'bench' }
    })
  })
})

describe('projectItems and teamItems', () => {
  const groups = [
    { team: team('t1', 'Rover Lab'), projects: [project('p1', 't1', 'Mars Rover')] },
    { team: team('t2', 'FSAE'), projects: [project('p2', 't2', 'Car 26')] }
  ]

  it('names each project with its team as detail', () => {
    expect(projectItems(groups)).toEqual([
      expect.objectContaining({
        key: 'project:p1',
        kind: 'project',
        label: 'Mars Rover',
        detail: 'Rover Lab',
        target: { type: 'project', project: { id: 'p1', name: 'Mars Rover', teamId: 't1' } }
      }),
      expect.objectContaining({ key: 'project:p2', detail: 'FSAE' })
    ])
  })

  it('lists teams with their project count', () => {
    expect(teamItems(groups)[0]).toMatchObject({
      key: 'team:t1',
      kind: 'team',
      label: 'Rover Lab',
      detail: '1 project',
      target: { type: 'team', teamId: 't1' }
    })
  })

  it('pluralises the project count', () => {
    const many = [
      { team: team('t3', 'Lab'), projects: [project('a', 't3', 'A'), project('b', 't3', 'B')] }
    ]
    expect(teamItems(many)[0].detail).toBe('2 projects')
  })
})

describe('nodeItems', () => {
  it('turns entities into node items scoped to the project', () => {
    expect(nodeItems('p1', [entity('e1', 'IMU', { type: 'sensor', domain: 'ee' })])).toEqual([
      {
        key: 'node:p1:e1',
        kind: 'node',
        label: 'IMU',
        detail: 'ee · sensor',
        keywords: ['sensor', 'ee'],
        target: { type: 'node', projectId: 'p1', entityId: 'e1' }
      }
    ])
  })

  it('drops entities that belong to another project', () => {
    const items = nodeItems('p1', [
      entity('e1', 'Mine', { project_id: 'p1' }),
      entity('e2', 'Theirs', { project_id: 'p2' })
    ])
    expect(items.map((item) => item.label)).toEqual(['Mine'])
  })

  it('names an unnamed entity by its type instead of rendering blank', () => {
    expect(nodeItems('p1', [entity('e1', '  ', { type: 'motor' })])[0].label).toBe('Unnamed motor')
  })

  it('returns nothing without entities', () => {
    expect(nodeItems('p1', null)).toEqual([])
  })
})
