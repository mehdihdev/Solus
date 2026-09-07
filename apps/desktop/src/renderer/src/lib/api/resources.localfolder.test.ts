// SOLUSDEV-249 (I2) — the local-folder routes (docs/api/local-folder.md §3):
// exact paths, methods and body shapes, and the `{source: null}` normalisation.
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import type { Source } from './resources'
import {
  getLocalFolder,
  isRootProject,
  linkLocalFolder,
  openLocalFolderEntity,
  type DetectedProject
} from './resources.localfolder'

function stubClient(result: unknown): {
  client: ApiClient
  calls: { path: string; options?: unknown }[]
} {
  const calls: { path: string; options?: unknown }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return result as never
    }),
    requestPage: vi.fn(async () => {
      throw new Error('unused')
    })
  }
  return { client, calls }
}

const MACHINE_ID = '0123456789abcdef0123456789abcdef'

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'syncing',
  config: { machine_id: MACHINE_ID, machine_name: 'mehdi-mbp', folder_name: 'rover-fw' },
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

describe('linkLocalFolder', () => {
  it('POSTs this machine and folder name to the dedicated route', async () => {
    const { client, calls } = stubClient({ source: SOURCE, job_id: 'j1' })
    const input = { machine_id: MACHINE_ID, machine_name: 'mehdi-mbp', folder_name: 'rover-fw' }

    const out = await linkLocalFolder('p 1', input, client)

    expect(calls).toEqual([
      { path: '/projects/p%201/local-folder', options: { method: 'POST', body: input } }
    ])
    expect(out.source.id).toBe('s1')
    expect(out.job_id).toBe('j1')
  })
})

describe('getLocalFolder', () => {
  it('GETs this machine’s view by machine_id', async () => {
    const view = {
      source: SOURCE,
      bridge: { connected: true, tools_installed: { kicad: true } },
      detected: []
    }
    const { client, calls } = stubClient(view)

    const out = await getLocalFolder('p1', MACHINE_ID, client)

    expect(calls[0].path).toBe(`/projects/p1/local-folder?machine_id=${MACHINE_ID}`)
    expect(calls[0].options).toBeUndefined()
    expect(out).toEqual(view)
  })

  it('normalises the bare {source: null} answer into an empty view', async () => {
    const { client } = stubClient({ source: null })

    const out = await getLocalFolder('p1', MACHINE_ID, client)

    expect(out).toEqual({
      source: null,
      bridge: { connected: false, tools_installed: {} },
      detected: []
    })
  })
})

describe('openLocalFolderEntity', () => {
  it('POSTs entity + tool to the source’s open route and returns the answer verbatim', async () => {
    const answer = { launched: false, tool: 'kicad', reason: 'KiCad is not installed' }
    const { client, calls } = stubClient(answer)

    const out = await openLocalFolderEntity('p1', 's/1', { entity_id: 'e1', tool: 'kicad' }, client)

    expect(calls).toEqual([
      {
        path: '/projects/p1/local-folder/s%2F1/open',
        options: { method: 'POST', body: { entity_id: 'e1', tool: 'kicad' } }
      }
    ])
    expect(out).toEqual(answer)
  })
})

describe('isRootProject', () => {
  const row = (over: Partial<DetectedProject>): DetectedProject => ({
    entity_id: 'e',
    entity_key: 'kicad:hw/main',
    tool: 'kicad',
    name: 'main',
    path: 'hw/main/main.kicad_pro',
    open_targets: [],
    ...over
  })
  it('recognises the clone/root node by its key or tool', () => {
    expect(isRootProject(row({ entity_key: 'clone:', tool: 'clone' }))).toBe(true)
    expect(isRootProject(row({ tool: 'local_clone' }))).toBe(true)
    expect(isRootProject(row({ tool: 'local_folder' }))).toBe(true)
    expect(isRootProject(row({}))).toBe(false)
  })
})
