import { api } from '../../../lib/api/client'
import type { JointBinding, SceneModel } from './types'
export interface ModelImport {
  robot_id: string
  artifact_id: string
  name: string
  format: 'urdf' | 'mjcf'
  source_entity_id?: string | null
  source_revision?: string | null
  meshes?: { reference: string; artifact_id: string }[]
  expected_version?: number
}
const path = (project: string): string =>
  `/projects/${encodeURIComponent(project)}/bench/scene/models`
function record(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function text(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0 && v.length <= 256
}
function vector(v: unknown): boolean {
  return (
    Array.isArray(v) &&
    v.length === 3 &&
    v.every((n: unknown) => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e6)
  )
}
function invalid(): never {
  throw new Error('The model response could not be verified.')
}
function optionalSource(value: Record<string, unknown>): boolean {
  return [value.source_entity_id, value.source_revision].every((v) => v == null || text(v))
}
function verifyHeader(value: Record<string, unknown>): void {
  if (
    !['id', 'robot_id', 'name', 'artifact_id'].every((key) => text(value[key])) ||
    !Number.isInteger(value.version) ||
    Number(value.version) < 1 ||
    typeof value.source_current !== 'boolean' ||
    !optionalSource(value) ||
    !record(value.model)
  )
    return invalid()
  verifyRefreshMetadata(value)
}
function verifyRefreshMetadata(value: Record<string, unknown>): void {
  if (
    value.refresh_status !== undefined &&
    (!text(value.refresh_status) ||
      !['current', 'queued', 'stale', 'error'].includes(value.refresh_status))
  )
    return invalid()
  if (value.refresh_error != null && !text(value.refresh_error)) return invalid()
  if (
    value.cad_bindings !== undefined &&
    (!Array.isArray(value.cad_bindings) ||
      value.cad_bindings.length > 64 ||
      !value.cad_bindings.every(
        (binding: unknown) =>
          record(binding) &&
          text(binding.mesh_key) &&
          text(binding.source_entity_id) &&
          (binding.observed_microversion === null || text(binding.observed_microversion))
      ))
  )
    return invalid()
}
function verifyModelArrays(model: Record<string, unknown>): void {
  if (
    !Array.isArray(model.links) ||
    model.links.length > 128 ||
    !Array.isArray(model.joints) ||
    model.joints.length > 128 ||
    !Array.isArray(model.warnings) ||
    model.warnings.length > 512 ||
    !model.warnings.every(text)
  )
    return invalid()
}
function verifyMeshes(model: Record<string, unknown>): void {
  let vertexCount = 0
  if (model.meshes !== undefined) {
    if (!record(model.meshes) || Object.keys(model.meshes).length > 64) return invalid()
    for (const mesh of Object.values(model.meshes)) {
      verifyMeshVertices(mesh)
      vertexCount += mesh.vertices.length
      if (
        vertexCount > 450000 ||
        !mesh.vertices.every(
          (n: unknown) => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e6
        )
      )
        return invalid()
    }
  }
}
function validMeshReference(key: unknown, meshes: unknown): boolean {
  return key == null || (text(key) && record(meshes) && Object.hasOwn(meshes, key))
}
function validVisualSize(size: unknown, kind: unknown): boolean {
  return (
    Array.isArray(size) &&
    size.length ===
      ({ box: 3, sphere: 1, cylinder: 2, mesh: 0 } as Record<string, number>)[String(kind)] &&
    size.every((n: unknown) => typeof n === 'number' && Number.isFinite(n) && n > 0 && n <= 1e6)
  )
}
function verifyVisual(visual: unknown, meshes: unknown): void {
  if (
    !record(visual) ||
    !['box', 'sphere', 'cylinder', 'mesh'].includes(String(visual.kind)) ||
    !vector(visual.xyz) ||
    !vector(visual.rpy) ||
    (visual.scale !== undefined && !vector(visual.scale)) ||
    !validMeshReference(visual.mesh_key, meshes) ||
    !validVisualSize(visual.size, visual.kind)
  )
    return invalid()
}
function verifyVisuals(model: Record<string, unknown>): void {
  let visualCount = 0
  for (const link of model.links as unknown[]) {
    if (!record(link) || !text(link.name) || !Array.isArray(link.visuals)) return invalid()
    visualCount += link.visuals.length
    for (const visual of link.visuals) verifyVisual(visual, model.meshes)
  }
  if (visualCount > 512) return invalid()
}
function validJointGeometry(joint: Record<string, unknown>): boolean {
  return (
    ['fixed', 'revolute', 'continuous', 'prismatic'].includes(String(joint.type)) &&
    [joint.xyz, joint.rpy, joint.axis].every(vector) &&
    [joint.lower, joint.upper].every(
      (n) => n === null || (typeof n === 'number' && Number.isFinite(n))
    )
  )
}
function verifyJoint(
  joint: unknown,
  names: Set<string>,
  parents: Map<string, string>,
  jointNames: Set<string>
): asserts joint is { name: string; parent: string; child: string } {
  if (
    !record(joint) ||
    !text(joint.name) ||
    jointNames.has(joint.name) ||
    !text(joint.parent) ||
    !text(joint.child) ||
    !names.has(joint.parent) ||
    !names.has(joint.child) ||
    parents.has(joint.child) ||
    !validJointGeometry(joint)
  )
    return invalid()
}
function verifyJoints(model: Record<string, unknown>): Set<string> {
  const names = new Set((model.links as { name: string }[]).map((link) => link.name)),
    parents = new Map<string, string>(),
    jointNames = new Set<string>()
  if (names.size !== (model.links as unknown[]).length) return invalid()
  for (const joint of model.joints as unknown[]) {
    verifyJoint(joint, names, parents, jointNames)
    jointNames.add(joint.name)
    parents.set(joint.child, joint.parent)
  }
  verifyAcyclic(names, parents)
  return jointNames
}
function verifyAcyclic(names: Set<string>, parents: Map<string, string>): void {
  for (const name of names) {
    const seen = new Set<string>()
    let current: string | undefined = name
    while (current !== undefined) {
      if (seen.has(current)) return invalid()
      seen.add(current)
      current = parents.get(current)
    }
  }
}
function verifyBindings(value: Record<string, unknown>, jointNames: Set<string>): void {
  if (
    !Array.isArray(value.bindings) ||
    value.bindings.length > 128 ||
    !value.bindings.every(
      (b: unknown) =>
        record(b) &&
        text(b.joint) &&
        jointNames.has(b.joint) &&
        ['part_entity_id', 'device_id', 'signal'].every((key) => text(b[key])) &&
        ['rad', 'deg', 'm'].includes(String(b.unit)) &&
        typeof b.scale === 'number' &&
        Number.isFinite(b.scale) &&
        typeof b.offset === 'number' &&
        Number.isFinite(b.offset)
    )
  )
    return invalid()
}
export function verifiedModel(value: unknown): SceneModel {
  if (!record(value)) return invalid()
  verifyHeader(value)
  const model = value.model as Record<string, unknown>
  verifyModelArrays(model)
  verifyMeshes(model)
  verifyVisuals(model)
  const jointNames = verifyJoints(model)
  verifyBindings(value, jointNames)
  return value as unknown as SceneModel
}
export async function listSceneModels(project: string): Promise<SceneModel[]> {
  const response = await api.request<{ models: unknown[] }>(path(project))
  if (!response || !Array.isArray(response.models) || response.models.length > 32)
    throw new Error('Invalid model list.')
  return response.models.map(verifiedModel)
}
export async function importSceneModel(
  project: string,
  input: ModelImport,
  id?: string
): Promise<SceneModel> {
  return verifiedModel(
    await api.request(`${path(project)}${id ? `/${encodeURIComponent(id)}` : ''}`, {
      method: id ? 'PUT' : 'POST',
      body: input
    })
  )
}
export async function confirmSceneMapping(
  project: string,
  model: SceneModel,
  bindings: JointBinding[]
): Promise<SceneModel> {
  return verifiedModel(
    await api.request(`${path(project)}/${encodeURIComponent(model.id)}/mapping`, {
      method: 'PUT',
      body: { expected_version: model.version, bindings }
    })
  )
}

function verifyMeshVertices(mesh: unknown): asserts mesh is { vertices: unknown[] } {
  if (
    !record(mesh) ||
    !Array.isArray(mesh.vertices) ||
    mesh.vertices.length % 9 !== 0 ||
    mesh.vertices.length === 0
  )
    return invalid()
}
