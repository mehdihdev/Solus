import { useEffect, useState } from 'react'
import { getHardwareConfig } from '../../../lib/api/hardware'
import { readHardwareTopology } from '../../../lib/api/hardwareTopology'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { confirmSceneMapping } from './sceneApi'
import type { JointBinding, SceneModel } from './types'
interface PartChoice {
  id: string
  name: string
  device: string
}
const PREFIX: Record<string, string> = {
  usb_serial: 'usb',
  usb_can: 'can',
  ble: 'ble',
  bt_classic: 'bt',
  wifi: 'ip',
  ethernet: 'ip',
  ros2: 'ros2'
}
export function MappingReview({
  projectId,
  model,
  onSaved
}: {
  projectId: string
  model: SceneModel
  onSaved: () => void
}): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  const [open, setOpen] = useState(false)
  const [reviewVersion, setReviewVersion] = useState(model.version)
  const [parts, setParts] = useState<PartChoice[]>([])
  const [draft, setDraft] = useState<JointBinding[]>(model.bindings)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!open) return
    let live = true
    void Promise.all([
      getHardwareConfig(projectId, model.robot_id),
      readHardwareTopology(projectId, model.robot_id)
    ]).then(
      ([result, topology]) => {
        if (!live || generation !== workspaceSessionGeneration()) return
        const identity = result.config.identity
        const prefix = identity ? PREFIX[identity.kind] : undefined
        const accepted = (result.config.bus_map ?? []).filter(
          (row) => row.part_entity_id !== null && row.part_entity_id !== undefined
        )
        setParts(
          identity && prefix
            ? accepted.map((row) => ({
                id: row.part_entity_id!,
                name:
                  topology.nodes.find((node) => node.id === row.part_entity_id)?.name ??
                  row.part_entity_id!,
                device: `${prefix}:${identity.binding}/${row.address}`
              }))
            : []
        )
      },
      () => {
        if (live) setError('Accepted hardware mappings could not be loaded.')
      }
    )
    return () => {
      live = false
    }
  }, [open, projectId, model.robot_id, generation])
  function change(joint: string, update: Partial<JointBinding>): void {
    const old = draft.find((binding) => binding.joint === joint)
    const type = model.model.joints.find((item) => item.name === joint)?.type
    const next = {
      ...{
        joint,
        part_entity_id: '',
        device_id: '',
        signal: 'position',
        unit: type === 'prismatic' ? ('m' as const) : ('deg' as const),
        scale: 1,
        offset: 0
      },
      ...old,
      ...update
    }
    setDraft([...draft.filter((binding) => binding.joint !== joint), next])
  }
  async function confirm(): Promise<void> {
    if (busy || generation !== workspaceSessionGeneration() || reviewVersion !== model.version)
      return
    setBusy(true)
    setError(null)
    try {
      await confirmSceneMapping(
        projectId,
        model,
        draft.filter((binding) => binding.part_entity_id !== '')
      )
      if (generation === workspaceSessionGeneration()) {
        setOpen(false)
        onSaved()
      }
    } catch {
      if (generation === workspaceSessionGeneration())
        setError(
          'Mapping was not accepted. Reload changed hardware and check the selected joints, units and parts.'
        )
    } finally {
      if (generation === workspaceSessionGeneration()) setBusy(false)
    }
  }
  if (!open)
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(model.bindings)
          setReviewVersion(model.version)
          setOpen(true)
        }}
      >
        Review joint mapping for {model.name}
      </button>
    )
  return (
    <fieldset>
      <legend>Confirm model joints against accepted hardware</legend>
      <p>
        Only selected mappings drive this display. Scale and offset convert the selected telemetry
        unit before display.
      </p>
      {model.model.joints
        .filter((joint) => joint.type !== 'fixed')
        .map((joint) => {
          const binding = draft.find((item) => item.joint === joint.name)
          return (
            <div key={joint.name}>
              <strong>{joint.name}</strong>
              <select
                aria-label={`${joint.name} hardware part`}
                value={binding?.part_entity_id ?? ''}
                onChange={(event) => {
                  const part = parts.find((item) => item.id === event.target.value)
                  change(joint.name, {
                    part_entity_id: part?.id ?? '',
                    device_id: part?.device ?? ''
                  })
                }}
              >
                <option value="">Unmapped</option>
                {parts.map((part) => (
                  <option key={part.id} value={part.id}>
                    {part.name} · {part.device}
                  </option>
                ))}
              </select>
              <input
                aria-label={`${joint.name} signal`}
                value={binding?.signal ?? 'position'}
                maxLength={128}
                onChange={(event) => change(joint.name, { signal: event.target.value })}
              />
              <select
                aria-label={`${joint.name} telemetry unit`}
                value={binding?.unit ?? (joint.type === 'prismatic' ? 'm' : 'deg')}
                onChange={(event) =>
                  change(joint.name, { unit: event.target.value as JointBinding['unit'] })
                }
              >
                {(joint.type === 'prismatic' ? ['m'] : ['deg', 'rad']).map((unit) => (
                  <option key={unit}>{unit}</option>
                ))}
              </select>
              {(['scale', 'offset'] as const).map((key) => (
                <input
                  key={key}
                  aria-label={`${joint.name} ${key}`}
                  type="number"
                  step="0.01"
                  value={binding?.[key] ?? (key === 'scale' ? 1 : 0)}
                  onChange={(event) => {
                    if (Number.isFinite(event.target.valueAsNumber))
                      change(joint.name, { [key]: event.target.valueAsNumber })
                  }}
                />
              ))}
            </div>
          )
        })}
      {reviewVersion !== model.version && (
        <p role="status">
          Model changed. Close this review and reopen it before confirming a new mapping.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <button
        type="button"
        disabled={busy || reviewVersion !== model.version}
        onClick={() => void confirm()}
      >
        Confirm joint mapping
      </button>
      <button type="button" disabled={busy} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </fieldset>
  )
}
