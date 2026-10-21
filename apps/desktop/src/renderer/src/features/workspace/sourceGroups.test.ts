// How Home's SOURCES block groups a project's sources by tool, and pairs a
// local folder with the git source it is a clone of (SOLUSDEV-317). Pure.
import { describe, it, expect } from 'vitest'
import { pairLocalClone, type ToolGroup } from './sourceGroups'
import type { Source } from '../../lib/api/resources'

const src = (over: Partial<Source>): Source => ({
  id: 's',
  project_id: 'p1',
  type: 'github',
  name: 'n',
  status: 'connected',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})
const group = (key: string, held: Source[]): ToolGroup => ({ key, entry: null, linked: true, held })

describe('pairLocalClone', () => {
  it('moves a cloned folder right under its repo and marks both ends', () => {
    const gh = group('github', [src({ config: { repo: 'Org/FW' } })])
    const on = group('onshape', [src({ type: 'onshape' })])
    const local = group('local', [
      src({ type: 'local', name: 'mehdi-mbp', remote: { repo: 'org/fw', host: 'github' } })
    ])
    const out = pairLocalClone([gh, on, local])
    expect(out.map((g) => g.key)).toEqual(['github', 'local', 'onshape'])
    expect(out[0]).toMatchObject({ link: 'below', clonedOn: 'mehdi-mbp' })
    expect(out[1]).toMatchObject({ link: 'above', cloneOf: 'Org/FW' })
  })

  it('leaves the groups alone without a match, and never mutates its input', () => {
    const gh = group('github', [src({ config: { repo: 'org/fw' } })])
    const local = group('local', [
      src({ type: 'local', remote: { repo: 'org/other', host: 'github' } })
    ])
    const input = [local, gh]
    const out = pairLocalClone(input)
    expect(out.map((g) => g.key)).toEqual(['local', 'github'])
    expect(out[0].link).toBeUndefined()
    expect(input[1].link).toBeUndefined()
  })

  it('needs the same host as the git source’s tool', () => {
    const gl = group('gitlab', [src({ type: 'gitlab', config: { repo: 'org/fw' } })])
    const local = group('local', [
      src({ type: 'local', remote: { repo: 'org/fw', host: 'github' } })
    ])
    expect(pairLocalClone([gl, local])[1].cloneOf).toBeUndefined()
  })
})
