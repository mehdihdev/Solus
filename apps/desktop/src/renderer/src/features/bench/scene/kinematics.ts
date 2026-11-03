import {
  AxesHelper,
  BoxGeometry,
  BufferGeometry,
  Float32BufferAttribute,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  Line,
  LineBasicMaterial,
  SphereGeometry,
  Vector3,
  type Object3D
} from 'three'
import type { JointBinding, KinematicModel, SceneVisual } from './types'

export interface BuiltModel {
  root: Group
  links: Map<string, Group>
  joints: Map<string, Group>
}
function origin(object: Object3D, xyz: number[], rpy: number[]): void {
  object.position.set(xyz[0], xyz[1], xyz[2])
  // URDF roll/pitch/yaw is fixed-axis Rz(yaw) Ry(pitch) Rx(roll).
  object.rotation.set(rpy[0], rpy[1], rpy[2], 'ZYX')
}
function buildVisual(visual: SceneVisual, model: KinematicModel): Mesh | null {
  const vertices = visual.mesh_key ? model.meshes?.[visual.mesh_key]?.vertices : undefined
  if (visual.kind === 'mesh' && !vertices) return null
  const geometry = visualGeometry(visual, vertices)
  // Three cylinders are Y-aligned; URDF/MJCF cylinders are Z-aligned.
  if (visual.kind === 'cylinder') geometry.rotateX(Math.PI / 2)
  const mesh = new Mesh(geometry, new MeshStandardMaterial({ color: 0x76b6ab, roughness: 0.65 }))
  if (visual.kind === 'mesh') {
    geometry.computeVertexNormals()
    mesh.scale.fromArray(visual.scale ?? [1, 1, 1])
  }
  origin(mesh, visual.xyz, visual.rpy)
  return mesh
}
export function buildModel(model: KinematicModel, skeleton = false): BuiltModel {
  const root = new Group(),
    links = new Map<string, Group>(),
    joints = new Map<string, Group>()
  for (const link of model.links) {
    const group = buildLink(link, model, skeleton)
    links.set(link.name, group)
  }
  const children = new Set(model.joints.map((joint) => joint.child))
  for (const [name, link] of links) if (!children.has(name)) root.add(link)
  for (const joint of model.joints) {
    const fixed = new Group(),
      moving = new Group()
    origin(fixed, joint.xyz, joint.rpy)
    fixed.add(moving)
    const marker = new Mesh(
      new SphereGeometry(0.008, 12, 8),
      new MeshStandardMaterial({ color: 0x80d8c1 })
    )
    marker.name = `joint-marker:${joint.name}`
    moving.add(marker)
    const parent = links.get(joint.parent),
      child = links.get(joint.child)
    if (parent && child) {
      const segment = new Line(
        new BufferGeometry().setFromPoints([
          new Vector3(),
          new Vector3(...(joint.xyz as [number, number, number]))
        ]),
        new LineBasicMaterial({ color: 0x65c9b2 })
      )
      segment.name = `joint-segment:${joint.name}`
      parent.add(segment)
      parent.add(fixed)
      moving.add(child)
    }
    joints.set(joint.name, moving)
  }
  return { root, links, joints }
}
export function applyJoints(
  scene: BuiltModel,
  model: KinematicModel,
  values: Record<string, number>
): void {
  for (const joint of model.joints) {
    const moving = scene.joints.get(joint.name)
    if (!moving) continue
    moving.position.set(0, 0, 0)
    moving.quaternion.identity()
    let value = values[joint.name]
    if (!Number.isFinite(value) || joint.type === 'fixed') continue
    if (joint.lower !== null) value = Math.max(joint.lower, value)
    if (joint.upper !== null) value = Math.min(joint.upper, value)
    const axis = new Vector3(...(joint.axis as [number, number, number])).normalize()
    if (joint.type === 'prismatic') moving.position.copy(axis.multiplyScalar(value))
    else moving.quaternion.setFromAxisAngle(axis, value)
  }
}
export function jointValue(
  binding: JointBinding,
  point: { value: number; unit?: string | null; timestamp: string } | undefined,
  current: boolean,
  now: number
): number | null {
  if (!current || !point || point.unit !== binding.unit || !Number.isFinite(point.value))
    return null
  const age = now - Date.parse(point.timestamp)
  if (!Number.isFinite(age) || age < -1000 || age > 10000) return null
  const value = point.value * binding.scale + binding.offset
  if (!Number.isFinite(value)) return null
  return binding.unit === 'deg' ? (value * Math.PI) / 180 : value
}
export function disposeModel(scene: BuiltModel): void {
  scene.root.traverse((object) => {
    if (object instanceof Mesh || object instanceof AxesHelper || object instanceof Line) {
      object.geometry.dispose()
      const materials = Array.isArray(object.material) ? object.material : [object.material]
      materials.forEach((material) => material.dispose())
    }
  })
  scene.root.clear()
}

function visualGeometry(visual: SceneVisual, vertices: number[] | undefined): BufferGeometry {
  return visual.kind === 'mesh'
    ? new BufferGeometry().setAttribute('position', new Float32BufferAttribute(vertices!, 3))
    : visual.kind === 'box'
      ? new BoxGeometry(...(visual.size as [number, number, number]))
      : visual.kind === 'sphere'
        ? new SphereGeometry(visual.size[0], 16, 12)
        : new CylinderGeometry(visual.size[0], visual.size[0], visual.size[1], 16)
}

function buildLink(
  link: KinematicModel['links'][number],
  model: KinematicModel,
  skeleton: boolean
): Group {
  const group = new Group()
  group.name = link.name
  if (!skeleton) group.add(new AxesHelper(0.04))
  for (const visual of skeleton ? [] : link.visuals) {
    const mesh = buildVisual(visual, model)
    if (mesh) group.add(mesh)
  }
  return group
}
