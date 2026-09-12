// Synthetic account anchors (SOLUSDEV-250 P5 lane D): one `integration_account` node per
// account grant, concatenated upstream of an unmodified buildNavigationIndex so the real
// document roots become its children. Pure and deterministic; anchors never touch the API.
import { describe, expect, it } from 'vitest'
import type { Entity, Relation, Source } from '../../lib/api/resources'
import { buildNavigationIndex } from './navigation/graphIndex'
import { accountDocuments, isAccountAnchor, withAccountAnchors } from './accountAnchors'

const entity = (id: string, over: Partial<Entity> = {}): Entity => ({
  id,
  type: 'repository',
  domain: 'code',
  name: id,
  source_key: null,
  project_id: 'p1',
  ...over
})
const source = (id: string, over: Partial<Source> = {}): Source => ({
  id,
  project_id: 'p1',
  type: 'github',
  name: id,
  status: 'connected',
  config: {},
  account_login: 'octocat',
  connection_id: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})

const repoA = entity('a', { source_id: 's1' })
const repoB = entity('b', { source_id: 's2' })
const fileA = entity('a-file', { type: 'file', source_id: 's1' })
const solus = entity('solus', { type: 'solus_config', domain: 'project', source_id: null })
const containsFile: Relation = {
  id: 'r1',
  type: 'contains',
  from_entity_id: 'a',
  to_entity_id: 'a-file'
}

describe('withAccountAnchors', () => {
  it('groups roots by connection and hangs them under one anchor', () => {
    const sources = [source('s1', { connection_id: 'c1' }), source('s2', { connection_id: 'c1' })]
    const merged = withAccountAnchors([repoA, repoB, fileA, solus], [containsFile], sources)
    const anchors = merged.entities.filter((e) => isAccountAnchor(e.id))
    expect(anchors).toEqual([
      {
        id: 'account:c1',
        type: 'integration_account',
        domain: 'integration',
        name: 'octocat',
        source_key: null,
        project_id: 'p1',
        properties: { provider: 'github', account_login: 'octocat', source_ids: ['s1', 's2'] }
      }
    ])
    expect(merged.relations.filter((r) => r.id.startsWith('account:'))).toEqual([
      { id: 'account:c1:a', type: 'contains', from_entity_id: 'account:c1', to_entity_id: 'a' },
      { id: 'account:c1:b', type: 'contains', from_entity_id: 'account:c1', to_entity_id: 'b' }
    ])
    // The real snapshot is untouched: concatenated, never rewritten.
    expect(merged.entities.slice(0, 4)).toEqual([repoA, repoB, fileA, solus])
    expect(merged.relations[0]).toBe(containsFile)
  })

  it('falls back to the source id when the source holds its own credential', () => {
    const merged = withAccountAnchors(
      [repoA, repoB],
      [],
      [source('s1'), source('s2', { account_login: null, type: 'onshape' })]
    )
    expect(merged.entities.map((e) => e.id)).toEqual(['a', 'b', 'account:s1', 'account:s2'])
    expect(merged.entities[3]?.name).toBe('onshape')
  })

  it('leaves roots without a resolvable source as roots', () => {
    const orphan = entity('orphan', { source_id: 'gone' })
    const merged = withAccountAnchors([solus, orphan, repoA], [], [source('s1')])
    const index = buildNavigationIndex(merged.entities, merged.relations)
    expect(index.roots.map((e) => e.id)).toEqual(['solus', 'account:s1', 'orphan'])
  })

  it('adds no anchor for a source with zero roots', () => {
    const merged = withAccountAnchors([solus], [], [source('s1')])
    expect(merged).toEqual({ entities: [solus], relations: [] })
  })

  it('is deterministic: the same input yields identical ids and order', () => {
    const sources = [source('s1', { connection_id: 'c1' }), source('s2')]
    const first = withAccountAnchors([repoB, repoA], [], sources)
    const second = withAccountAnchors([repoB, repoA], [], sources)
    expect(first).toEqual(second)
    expect(first.entities.map((e) => e.id)).toEqual(['b', 'a', 'account:c1', 'account:s2'])
  })

  it('makes the roots the anchor’s children in the unmodified index, with a working pathTo', () => {
    const merged = withAccountAnchors(
      [repoA, fileA, solus],
      [containsFile],
      [source('s1', { connection_id: 'c1' })]
    )
    const index = buildNavigationIndex(merged.entities, merged.relations)
    expect(index.roots.map((e) => e.id)).toEqual(['solus', 'account:c1'])
    expect(index.children.get('account:c1')?.map((e) => e.id)).toEqual(['a'])
    expect(index.pathTo('a-file').map((step) => step.entity.id)).toEqual(['account:c1', 'a'])
    expect(index.crossLinks).toEqual([])
  })
})

describe('accountDocuments', () => {
  it('lists the anchor’s documents from the merged snapshot', () => {
    const merged = withAccountAnchors([repoA, repoB, fileA], [containsFile], [source('s1')])
    expect(accountDocuments('account:s1', merged.entities, merged.relations)).toEqual([repoA])
    expect(accountDocuments('account:none', merged.entities, merged.relations)).toEqual([])
  })
})

it('isAccountAnchor recognises only synthetic ids', () => {
  expect(isAccountAnchor('account:c1')).toBe(true)
  expect(isAccountAnchor('0199-uuid')).toBe(false)
})

describe('local folder and selected revision presentation', () => {
  it('shows ForgeTS as the root rather than its dependency packages', () => {
    const clone = entity('clone', { type: 'local_clone', name: 'ForgeTS', source_id: 'local' })
    const dependency = entity('dependency', { type: 'python_requirement', source_id: 'local' })
    const requires: Relation = {
      id: 'requires',
      type: 'requires',
      from_entity_id: clone.id,
      to_entity_id: dependency.id
    }
    const merged = withAccountAnchors(
      [clone, dependency],
      [requires],
      [source('local', { type: 'local', account_login: null })]
    )
    const index = buildNavigationIndex(merged.entities, merged.relations)
    expect(index.roots.map((item) => item.name)).toEqual(['ForgeTS'])
    expect(index.children.get(clone.id)?.map((item) => item.id)).toEqual(['dependency'])
    expect(merged.relations).toContainEqual(requires)
  })

  it('keeps snapshot roots under the existing repository account', () => {
    const snapshot = entity('snapshot-root', {
      source_id: 'internal',
      properties: { base_source_id: 's1' }
    })
    const merged = withAccountAnchors([snapshot], [], [source('s1', { connection_id: 'c1' })])
    expect(accountDocuments('account:c1', merged.entities, merged.relations)).toEqual([snapshot])
    expect(
      merged.entities.find((item) => item.id === 'account:c1')?.properties?.source_ids
    ).toEqual(['s1'])
  })
})
