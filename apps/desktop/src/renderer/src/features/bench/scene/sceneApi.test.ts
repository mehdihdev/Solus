import { describe, expect, it } from 'vitest'
import { verifiedModel } from './sceneApi'
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
