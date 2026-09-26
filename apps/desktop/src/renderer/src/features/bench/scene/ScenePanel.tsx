import { CadBindings } from './CadBindings'
import { CadImport } from './CadImport'
import { useEffect, useState } from 'react'
import { listEntities, uploadArtifact, type Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { SceneViewer } from './SceneViewer'
import { loadPose, poseKey, savePose, ZERO_POSE, type DisplayPose } from './displayPose'
import { importSceneModel, listSceneModels } from './sceneApi'
import { useSceneValues } from './useSceneValues'
import { MappingReview } from './MappingReview'
import type { SceneModel } from './types'

export function ScenePanel({
  projectId,
  paused = false,
  compact = false
}: {
  projectId: string
  paused?: boolean
  compact?: boolean
}): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  const user = useAuthStore((state) => state.user?.email ?? null)
  return (
    <ScopedScenePanel
      key={JSON.stringify([user, projectId, generation])}
      projectId={projectId}
      paused={paused}
      compact={compact}
      generation={generation}
      user={user}
    />
  )
}
function ScopedScenePanel({
  projectId,
  generation,
  user,
  paused,
  compact
}: {
  projectId: string
  generation: number
  user: string | null
  paused: boolean
  compact: boolean
}): React.JSX.Element {
  const [spawning, setSpawning] = useState(!compact)
  const [models, setModels] = useState<SceneModel[]>([])
  const [robots, setRobots] = useState<Entity[]>([])
  const [robotId, setRobotId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [meshes, setMeshes] = useState<{ file: File; reference: string }[]>([])
  const [format, setFormat] = useState<'urdf' | 'mjcf'>('urdf')
  const [revision, setRevision] = useState('')
  const [replaceId, setReplaceId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [poses, setPoses] = useState<Record<string, DisplayPose>>({})
  const [refresh, setRefresh] = useState(0)
  const values = useSceneValues(projectId, models, generation, paused)
  useEffect(() => {
    if (paused) return
    let live = true,
      inFlight = false
    async function load(): Promise<void> {
      if (inFlight) return
      inFlight = true
      try {
        const [next, entities] = await Promise.all([
          listSceneModels(projectId),
          listEntities(projectId, { type: 'physical_robot', limit: 100 })
        ])
        if (!live || workspaceSessionGeneration() !== generation) return
        setModels((old) => (JSON.stringify(old) === JSON.stringify(next) ? old : next))
        setRobots(
          entities.filter(
            (robot) => robot.project_id === projectId && robot.type === 'physical_robot'
          )
        )
        setPoses((old) =>
          Object.fromEntries(
            next.map((model) => [
              model.id,
              old[model.id] ?? loadPose(poseKey(user, projectId, model.id))
            ])
          )
        )
      } catch {
        if (live) setError('Scene models could not be loaded.')
      } finally {
        inFlight = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), 10000)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [projectId, generation, user, refresh, paused])
  async function importFile(): Promise<void> {
    if (!file || !robotId || busy) return
    const validationError = validateImport(file, meshes)
    if (validationError) {
      setError(validationError)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const imported = await uploadModel({
        projectId,
        file,
        robotId,
        meshes,
        generation,
        models,
        replaceId,
        revision,
        format
      })
      if (!imported) return
      if (workspaceSessionGeneration() === generation) {
        setRefresh((n) => n + 1)
        setFile(null)
      }
    } catch {
      if (workspaceSessionGeneration() === generation)
        setError(
          'The model could not be imported. Check its format, size and saved robot; reloading resolves concurrent edits.'
        )
    } finally {
      if (workspaceSessionGeneration() === generation) setBusy(false)
    }
  }
  function place(model: SceneModel, kind: keyof DisplayPose, axis: number, value: number): void {
    if (!Number.isFinite(value) || Math.abs(value) > 10000) return
    const before = poses[model.id] ?? ZERO_POSE
    const next = { ...before, [kind]: before[kind].map((n, i) => (i === axis ? value : n)) }
    setPoses((old) => ({ ...old, [model.id]: next }))
    if (!savePose(poseKey(user, projectId, model.id), next))
      setError('Display placement could not be saved on this machine.')
  }
  return (
    <section
      aria-label="Robot scene"
      className={compact ? 'bench-scene' : undefined}
      style={compact ? undefined : { overflow: 'auto', padding: 20 }}
    >
      <div className="bench-section-heading">
        <span>SCENE</span>
        <button onClick={() => setSpawning(!spawning)} aria-expanded={spawning}>
          + Spawn
        </button>
      </div>
      <SceneViewer models={models} poses={poses} values={values} compact={compact} />
      {models.length === 0 && <p>No models imported yet.</p>}
      <SceneStatus paused={paused} values={values} models={models} />
      {spawning && (
        <div>
          <p>
            Kinematic display. Orbit with the pointer; scroll to zoom. Import files from this
            computer.
          </p>
          <label>
            Robot for model
            <select
              aria-label="Robot for model"
              value={robotId}
              onChange={(event) => setRobotId(event.target.value)}
            >
              <option value="">Select robot</option>
              {robots.map((robot) => (
                <option key={robot.id} value={robot.id}>
                  {robot.name}
                </option>
              ))}
            </select>
          </label>
          <CadImport
            projectId={projectId}
            robotId={robotId}
            onImported={() => setRefresh((n) => n + 1)}
          />
          <label>
            Local URDF or MJCF
            <input
              aria-label="Local URDF or MJCF"
              type="file"
              accept=".urdf,.xml,.mjcf"
              onChange={(event) => {
                const selected = event.target.files?.[0] ?? null
                setFile(selected)
                if (selected?.name.endsWith('.mjcf')) setFormat('mjcf')
              }}
            />
          </label>
          <label>
            Local STL assets
            <input
              aria-label="Local STL assets"
              type="file"
              accept=".stl"
              multiple
              onChange={(event) =>
                setMeshes(
                  Array.from(event.target.files ?? [])
                    .slice(0, 65)
                    .map((selected) => ({ file: selected, reference: selected.name }))
                )
              }
            />
          </label>
          {meshes.map((mesh, index) => (
            <label key={index}>
              Reference for {mesh.file.name}
              <input
                aria-label={`Reference for ${mesh.file.name}`}
                maxLength={512}
                value={mesh.reference}
                onChange={(event) =>
                  setMeshes((old) =>
                    old.map((item, at) =>
                      at === index ? { ...item, reference: event.target.value } : item
                    )
                  )
                }
              />
            </label>
          ))}
          {meshes.length > 0 && (
            <p>
              Use the exact mesh filename/reference from the model. These selected files are
              uploaded; no referenced path is opened automatically.
            </p>
          )}
          <select
            aria-label="Model format"
            value={format}
            onChange={(event) => setFormat(event.target.value as 'urdf' | 'mjcf')}
          >
            <option value="urdf">URDF</option>
            <option value="mjcf">MJCF</option>
          </select>
          <input
            aria-label="Source revision"
            placeholder="Source revision (optional)"
            maxLength={128}
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
          />
          <select
            aria-label="Replace model"
            value={replaceId}
            onChange={(event) => {
              setReplaceId(event.target.value)
              const model = models.find((m) => m.id === event.target.value)
              if (model) setRobotId(model.robot_id)
            }}
          >
            <option value="">Add model</option>
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                Reimport {model.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!file || !robotId || busy}
            onClick={() => void importFile()}
          >
            {busy ? 'Importing…' : 'Import model'}
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <SceneSettings compact={compact}>
        {models.map((model) => (
          <article key={model.id} aria-label={model.name}>
            <h3>{model.name}</h3>
            <CadBindings
              projectId={projectId}
              model={model}
              onSaved={() => setRefresh((v) => v + 1)}
            />
            <p>
              Revision {model.source_revision ?? model.version} ·{' '}
              {model.model.joints.filter((joint) => joint.type !== 'fixed').length} moving joints
            </p>
            {!model.source_current && (
              <p role="status">
                Source or hardware mapping changed. Reimport or review the mapping before displaying
                live movement.
              </p>
            )}
            {!model.model.joints.some((joint) => joint.type !== 'fixed') && (
              <p>No moving joints are declared. This model is displayed as static geometry.</p>
            )}
            {model.model.warnings.map((warning, index) => (
              <p key={index} role="status">
                {warning}
              </p>
            ))}
            {(['translation', 'rotation'] as const).map((kind) => (
              <fieldset key={kind}>
                <legend>
                  Display {kind} ({kind === 'translation' ? 'm' : 'rad'})
                </legend>
                {['X', 'Y', 'Z'].map((axis, index) => (
                  <label key={axis}>
                    {axis}
                    <input
                      aria-label={`${model.name} ${kind} ${axis}`}
                      type="number"
                      step="0.1"
                      min="-10000"
                      max="10000"
                      value={(poses[model.id] ?? ZERO_POSE)[kind][index]}
                      onChange={(event) => place(model, kind, index, event.target.valueAsNumber)}
                    />
                  </label>
                ))}
              </fieldset>
            ))}
            {model.model.joints.some((joint) => joint.type !== 'fixed') && (
              <MappingReview
                projectId={projectId}
                model={model}
                onSaved={() => setRefresh((n) => n + 1)}
              />
            )}
          </article>
        ))}
      </SceneSettings>
    </section>
  )
}

function SceneSettings({
  compact,
  children
}: {
  compact: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return compact ? (
    <details>
      <summary>Scene settings</summary>
      {children}
    </details>
  ) : (
    <>{children}</>
  )
}

function SceneStatus({
  paused,
  values,
  models
}: {
  paused: boolean
  values: Record<string, Record<string, number>>
  models: SceneModel[]
}): React.JSX.Element {
  return (
    <>
      {' '}
      <div className="bench-section-heading">
        <span>
          {paused
            ? 'PAUSED'
            : Object.values(values).some((joints) => Object.keys(joints).length)
              ? 'LIVE'
              : 'NO LIVE MAPPING'}
        </span>
        <span>
          {models.length && models.every((model) => model.source_current)
            ? 'MAPPING CURRENT'
            : 'UNMAPPED'}
        </span>
      </div>
      <p className="bench-scene-caption">
        {models.some((model) => model.cad_bindings?.length)
          ? 'SCENE LINKED TO CAD — UPDATES WHEN THE CAD CHANGES'
          : 'NO CAD LINK — IMPORT A MODEL TO SEE ITS GEOMETRY'}
      </p>
    </>
  )
}

type ImportMesh = { file: File; reference: string }
function validateImport(file: File, meshes: ImportMesh[]): string | null {
  if (file.size > 1024 * 1024) return 'Model XML must be at most 1 MiB.'
  if (
    meshes.length > 64 ||
    meshes.reduce((sum, mesh) => sum + mesh.file.size, file.size) > 8 * 1024 * 1024 ||
    meshes.some((mesh) => !mesh.reference.trim())
  )
    return 'Choose at most 64 mesh files, with exact model references and at most 8 MiB total.'
  return null
}
async function uploadMeshes(
  projectId: string,
  meshes: ImportMesh[],
  generation: number
): Promise<{ reference: string; artifact_id: string }[] | null> {
  const artifacts: { reference: string; artifact_id: string }[] = []
  for (const mesh of meshes) {
    const uploaded = await uploadArtifact(projectId, mesh.file)
    if (workspaceSessionGeneration() !== generation) return null
    artifacts.push({ reference: mesh.reference.trim(), artifact_id: uploaded.artifact_id })
  }
  return artifacts
}

async function uploadModel({
  projectId,
  file,
  robotId,
  meshes,
  generation,
  models,
  replaceId,
  revision,
  format
}: {
  projectId: string
  file: File
  robotId: string
  meshes: ImportMesh[]
  generation: number
  models: SceneModel[]
  replaceId: string
  revision: string
  format: 'urdf' | 'mjcf'
}): Promise<boolean> {
  const artifact = await uploadArtifact(projectId, file)
  if (workspaceSessionGeneration() !== generation) return false
  const meshArtifacts = await uploadMeshes(projectId, meshes, generation)
  if (!meshArtifacts || workspaceSessionGeneration() !== generation) return false
  const previous = models.find((model) => model.id === replaceId)
  await importSceneModel(
    projectId,
    {
      robot_id: robotId,
      artifact_id: artifact.artifact_id,
      name: file.name.slice(0, 120),
      format,
      meshes: meshArtifacts,
      source_revision: revision.trim() || null,
      ...(previous
        ? { expected_version: previous.version, source_entity_id: previous.source_entity_id }
        : {})
    },
    replaceId || undefined
  )
  return true
}
