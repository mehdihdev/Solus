// The git repos linked to each project, for Home's project list
// (SOLUSDEV-317): read once per project from its sources, a failure leaves
// that project without a line — never a guess.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { linkedRepos, useProjectRepos } from './useProjectRepos'
import * as resources from '../../lib/api/resources'
import * as online from './workspaceOnline'
import type { Source } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, listSources: vi.fn() }
})
vi.mock('./workspaceOnline', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./workspaceOnline')>()
  return { ...actual, useWorkspaceFetchEnabled: vi.fn(() => true) }
})

const source = (over: Partial<Source>): Source => ({
  id: 's1',
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

beforeEach(() => vi.clearAllMocks())

describe('linkedRepos', () => {
  it('keeps sources that name a repo, with their provider, in order', () => {
    expect(
      linkedRepos([
        source({ config: { repo: 'mehdihdev/lerobot-arm' } }),
        source({ id: 's2', type: 'onshape', config: { documents: ['d1'] } }),
        source({ id: 's3', type: 'gitlab', config: { repo: 'group/fw' } }),
        source({ id: 's4', config: { repo: '' } })
      ])
    ).toEqual([
      { provider: 'github', repo: 'mehdihdev/lerobot-arm' },
      { provider: 'gitlab', repo: 'group/fw' }
    ])
  })
})

describe('useProjectRepos', () => {
  it('reads each project once and leaves out a project whose read failed', async () => {
    vi.mocked(resources.listSources).mockImplementation(async (id) => {
      if (id === 'p2') throw new Error('nope')
      return [source({ project_id: id, config: { repo: `org/${id}` } })]
    })
    const { result, rerender } = renderHook(({ ids }) => useProjectRepos(ids), {
      initialProps: { ids: ['p1', 'p2'] }
    })
    await waitFor(() => expect(result.current.p1).toEqual([{ provider: 'github', repo: 'org/p1' }]))
    expect(result.current.p2).toBeUndefined()
    rerender({ ids: ['p1', 'p2'] })
    expect(resources.listSources).toHaveBeenCalledTimes(2)
  })

  it('reads nothing while fetching is off', () => {
    vi.mocked(online.useWorkspaceFetchEnabled).mockReturnValue(false)
    const { result } = renderHook(() => useProjectRepos(['p1']))
    expect(result.current).toEqual({})
    expect(resources.listSources).not.toHaveBeenCalled()
  })
})
