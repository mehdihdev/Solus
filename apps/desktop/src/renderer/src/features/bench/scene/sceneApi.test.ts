import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import { listSharedSceneModels, sameSceneModels, verifiedModel } from './sceneApi'
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn() } }))
const base = {
  id: 'm',
  robot_id: 'r',
  name: 'Model',
  artifact_id: 'a',
  version: 1,
  source_current: true,
  bindings: [],
  model: { links: [{ name: 'base', visuals: [] }], joints: [], warnings: [] }
}
describe('scene response validation', () => {
  it('rejects nonfinite/oversized mesh buffers before the renderer allocates GPU data', () => {
    for (const vertices of [[NaN, 0, 0], [1, 2], Array(450009).fill(0)]) {
      expect(() =>
        verifiedModel({ ...base, model: { ...base.model, meshes: { key: { vertices } } } })
      ).toThrow()
    }
  })
  it('rejects cyclic link graphs', () => {
    expect(() =>
      verifiedModel({
        ...base,
        model: {
          ...base.model,
          joints: [
            {
              name: 'loop',
              type: 'fixed',
              parent: 'base',
              child: 'base',
              xyz: [0, 0, 0],
              rpy: [0, 0, 0],
              axis: [1, 0, 0],
              lower: null,
              upper: null
            }
          ]
        }
      })
    ).toThrow()
  })
  it('accepts bounded mesh geometry and primitive models', () => {
    expect(verifiedModel(base).id).toBe('m')
    expect(
      verifiedModel({
        ...base,
        model: { ...base.model, meshes: { key: { vertices: [0, 0, 0, 1, 0, 0, 0, 1, 0] } } }
      }).id
    ).toBe('m')
  })
})

it('rejects object-valued source metadata before React renders it', () => {
  expect(() => verifiedModel({ ...base, source_revision: { bad: true } })).toThrow()
  expect(() => verifiedModel({ ...base, source_entity_id: 123 })).toThrow()
})

describe('shared scene model listing', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.mocked(api.request).mockReset()
    vi.mocked(api.request).mockResolvedValue({ models: [base] })
  })
  it('lets every panel on a project share one multi-megabyte listing', async () => {
    const [a, b] = await Promise.all([
      listSharedSceneModels('p-share'),
      listSharedSceneModels('p-share')
    ])
    expect(api.request).toHaveBeenCalledTimes(1)
    expect(a).toBe(b)
  })
  it('fetches again once the shared listing is older than the poll window', async () => {
    vi.useFakeTimers()
    await listSharedSceneModels('p-age')
    vi.advanceTimersByTime(6000)
    await listSharedSceneModels('p-age')
    expect(api.request).toHaveBeenCalledTimes(2)
  })
  it('bypasses the shared listing when a panel needs fresh models after an edit', async () => {
    await listSharedSceneModels('p-fresh')
    await listSharedSceneModels('p-fresh', { fresh: true })
    expect(api.request).toHaveBeenCalledTimes(2)
  })
  it('does not keep a failed listing for the next caller', async () => {
    vi.mocked(api.request).mockRejectedValueOnce(new Error('offline'))
    await expect(listSharedSceneModels('p-fail')).rejects.toThrow()
    await expect(listSharedSceneModels('p-fail')).resolves.toHaveLength(1)
  })
})
describe('scene model comparison', () => {
  const binding = {
    joint: 'j',
    part_entity_id: 'part',
    device_id: 'dev',
    signal: 's',
    unit: 'deg' as const,
    scale: 1,
    offset: 0
  }
  const model = verifiedModel(base)
  it('treats a refetched, unchanged listing as the same', () => {
    expect(sameSceneModels([model], [verifiedModel(structuredClone(base))])).toBe(true)
  })
  it('sees a new version, status or binding without comparing mesh geometry', () => {
    expect(sameSceneModels([model], [{ ...model, version: 2 }])).toBe(false)
    expect(sameSceneModels([model], [{ ...model, refresh_status: 'queued' }])).toBe(false)
    expect(sameSceneModels([model], [{ ...model, bindings: [{ ...binding, offset: 1 }] }])).toBe(
      false
    )
    expect(sameSceneModels([model], [])).toBe(false)
  })
})
