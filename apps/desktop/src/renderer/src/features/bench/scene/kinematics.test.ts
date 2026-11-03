import { describe, expect, it } from 'vitest'
import { Vector3 } from 'three'
import { buildModel, applyJoints, jointValue, disposeModel } from './kinematics'

const model = {
  links: [
    { name: 'base', visuals: [] },
    {
      name: 'arm',
      visuals: [{ kind: 'box' as const, size: [1, 0.1, 0.1], xyz: [0.5, 0, 0], rpy: [0, 0, 0] }]
    }
  ],
  joints: [
    {
      name: 'hinge',
      type: 'revolute' as const,
      parent: 'base',
      child: 'arm',
      xyz: [1, 0, 0],
      rpy: [0, 0, 0],
      axis: [0, 0, 1],
      lower: -Math.PI,
      upper: Math.PI
    }
  ],
  warnings: []
}

describe('client kinematics', () => {
  it('applies joint rotation after the fixed joint origin without accumulating', () => {
    const scene = buildModel(model)
    applyJoints(scene, model, { hinge: Math.PI / 2 })
    scene.root.updateMatrixWorld(true)
    const point = scene.links.get('arm')!.localToWorld(new Vector3(1, 0, 0))
    expect(point.x).toBeCloseTo(1)
    expect(point.y).toBeCloseTo(1)
    applyJoints(scene, model, { hinge: 0 })
    scene.root.updateMatrixWorld(true)
    expect(scene.links.get('arm')!.localToWorld(new Vector3(1, 0, 0)).x).toBeCloseTo(2)
    disposeModel(scene)
  })
  it('keeps independently imported models isolated', () => {
    const first = buildModel(model),
      second = buildModel(model)
    applyJoints(first, model, { hinge: 1 })
    expect(second.joints.get('hinge')!.quaternion.z).toBe(0)
    disposeModel(first)
    disposeModel(second)
  })
  it('uses only current confirmed mappings, matching units and fresh values', () => {
    const binding = {
      joint: 'hinge',
      part_entity_id: 'part',
      device_id: 'device',
      signal: 'position',
      unit: 'deg' as const,
      scale: 1,
      offset: 0
    }
    expect(
      jointValue(
        binding,
        { value: 90, unit: 'deg', timestamp: new Date(1000).toISOString() },
        true,
        2000
      )
    ).toBeCloseTo(Math.PI / 2)
    expect(
      jointValue(
        binding,
        { value: 90, unit: 'A', timestamp: new Date(1000).toISOString() },
        true,
        2000
      )
    ).toBeNull()
    expect(
      jointValue(
        binding,
        { value: 90, unit: 'deg', timestamp: new Date(1000).toISOString() },
        false,
        2000
      )
    ).toBeNull()
    expect(
      jointValue(
        binding,
        { value: 90, unit: 'deg', timestamp: new Date(1000).toISOString() },
        true,
        20000
      )
    ).toBeNull()
    expect(
      jointValue(
        binding,
        { value: Infinity, unit: 'deg', timestamp: new Date(1000).toISOString() },
        true,
        2000
      )
    ).toBeNull()
  })
  it('supports prismatic displacement and clamps to declared limits', () => {
    const sliding = {
      ...model,
      joints: [
        { ...model.joints[0], type: 'prismatic' as const, axis: [1, 0, 0], lower: 0, upper: 0.5 }
      ]
    }
    const scene = buildModel(sliding)
    applyJoints(scene, sliding, { hinge: 10 })
    expect(scene.joints.get('hinge')!.position.x).toBeCloseTo(0.5)
    disposeModel(scene)
  })
})

it('renders explicitly supplied mesh vertices with per-visual scale', () => {
  const imported = {
    links: [
      {
        name: 'part',
        visuals: [
          {
            kind: 'mesh' as const,
            size: [],
            xyz: [0, 0, 0],
            rpy: [0, 0, 0],
            mesh_key: 'mesh',
            scale: [0.001, 0.001, 0.001]
          }
        ]
      }
    ],
    joints: [],
    warnings: [],
    meshes: { mesh: { vertices: [0, 0, 0, 100, 0, 0, 0, 100, 0] } }
  }
  const scene = buildModel(imported)
  const mesh = scene.links.get('part')!.children.find((child) => child.type === 'Mesh')
  expect(mesh).toBeDefined()
  expect(mesh!.scale.x).toBe(0.001)
  disposeModel(scene)
})

it('draws joint markers and segments only at declared model transforms', () => {
  const scene = buildModel(model)
  const marker = scene.root.getObjectByName('joint-marker:hinge')
  expect(marker).toBeDefined()
  scene.root.updateMatrixWorld(true)
  expect(marker?.getWorldPosition(new Vector3()).toArray()).toEqual([1, 0, 0])
  expect(scene.root.getObjectByName('joint-segment:hinge')).toBeDefined()
  disposeModel(scene)
})
