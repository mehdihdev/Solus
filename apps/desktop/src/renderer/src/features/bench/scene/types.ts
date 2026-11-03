export interface SceneVisual {
  mesh_key?: string | null
  scale?: number[]
  kind: 'box' | 'sphere' | 'cylinder' | 'mesh'
  size: number[]
  xyz: number[]
  rpy: number[]
}
export interface SceneJoint {
  name: string
  type: 'fixed' | 'revolute' | 'continuous' | 'prismatic'
  parent: string
  child: string
  xyz: number[]
  rpy: number[]
  axis: number[]
  lower: number | null
  upper: number | null
}
export interface KinematicModel {
  meshes?: Record<string, { vertices: number[] }>
  links: { name: string; visuals: SceneVisual[] }[]
  joints: SceneJoint[]
  warnings: string[]
}
export interface JointBinding {
  joint: string
  part_entity_id: string
  device_id: string
  signal: string
  unit: 'deg' | 'rad' | 'm'
  scale: number
  offset: number
}
export interface SceneModel {
  cad_bindings?: {
    mesh_key: string
    source_entity_id: string
    observed_microversion: string | null
  }[]
  refresh_status?: 'current' | 'queued' | 'stale' | 'error'
  refresh_error?: string | null
  id: string
  robot_id: string
  name: string
  version: number
  artifact_id: string
  source_entity_id: string | null
  source_revision: string | null
  source_current: boolean
  model: KinematicModel
  bindings: JointBinding[]
}
