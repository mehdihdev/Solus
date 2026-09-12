import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import type { Entity } from './resources'
import {
  createPhysicalRobot,
  renamePhysicalRobot,
  deletePhysicalRobot,
  listRobotOrphans
} from './physicalRobots'

const robot: Entity = {
  id: 'r1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  origin: 'manual',
  source_id: null,
  version: 4
}
const client = (): ApiClient => ({ request: vi.fn(), requestPage: vi.fn() })

describe('physical robot API', () => {
  it('creates independent default-name instances without an ensure or provider request', async () => {
    const api = client()
    vi.mocked(api.request)
      .mockResolvedValueOnce(robot)
      .mockResolvedValueOnce({ ...robot, id: 'r2' })
    expect((await createPhysicalRobot('p1', api)).id).toBe('r1')
    expect((await createPhysicalRobot('p1', api)).id).toBe('r2')
    expect(api.request).toHaveBeenCalledTimes(2)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/entities', {
      method: 'POST',
      body: { type: 'physical_robot' }
    })
  })

  it('sends a name only when one is given', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue(robot)
    await createPhysicalRobot('p1', api, 'Rover')
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/entities', {
      method: 'POST',
      body: { type: 'physical_robot', name: 'Rover' }
    })
    await createPhysicalRobot('p1', api, '')
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/entities', {
      method: 'POST',
      body: { type: 'physical_robot' }
    })
  })

  it('renames and removes with the exact entity version', async () => {
    const api = client()
    await renamePhysicalRobot('p1', robot, 'Leader', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/entities/r1', {
      method: 'PATCH',
      body: { name: 'Leader' },
      ifMatch: 4
    })
    const retained = { deleted_entity_id: 'r1', retained_part_ids: ['part'] }
    vi.mocked(api.request).mockResolvedValue(retained)
    expect(await deletePhysicalRobot('p1', robot, api)).toEqual(retained)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/entities/r1', {
      method: 'DELETE',
      ifMatch: 4
    })
  })

  it.each([undefined, -1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
    'refuses missing or invalid versions (%s) before a mutation',
    async (version) => {
      const api = client()
      await expect(deletePhysicalRobot('p1', { ...robot, version }, api)).rejects.toThrow(
        /version/i
      )
      expect(api.request).not.toHaveBeenCalled()
    }
  )

  it('preserves conflicts without automatically retrying a mutation', async () => {
    const api = client()
    vi.mocked(api.request).mockRejectedValue(new ApiError(409, 'conflict', 'Robot changed'))
    await expect(renamePhysicalRobot('p1', robot, 'Leader', api)).rejects.toMatchObject({
      status: 409
    })
    expect(api.request).toHaveBeenCalledTimes(1)
  })

  it('reads bounded persistent orphan pages and escapes the cursor', async () => {
    const api = client()
    const page = { data: [{ id: 'part' }], meta: { has_next: false } }
    vi.mocked(api.requestPage).mockResolvedValue(page)
    expect(await listRobotOrphans('p1', null, api)).toBe(page)
    expect(api.requestPage).toHaveBeenLastCalledWith(
      '/projects/p1/entities?orphaned_from_robot=true&limit=24'
    )
    await listRobotOrphans('p1', 'next/+?', api)
    expect(api.requestPage).toHaveBeenLastCalledWith(
      '/projects/p1/entities?orphaned_from_robot=true&limit=24&cursor=next%2F%2B%3F'
    )
  })
})
