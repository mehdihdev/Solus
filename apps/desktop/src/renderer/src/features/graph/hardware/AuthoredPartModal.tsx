// Flow 5 — Authored (docs/wireflows/hardware-onboarding.md): name, target robot
// (existing or a new Physical Robot created first through the same service),
// category, the category's generic spec fields, lifecycle → POST /parts.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import {
  LIFECYCLE_STATES,
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  createHardwarePart,
  type LifecycleState,
  type PartIn,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { MODAL_INPUT_STYLE, ModalShell } from '../../workspace/modals'
import { HARDWARE_COPY, HARDWARE_SPEC_FIELDS } from './hardware.constants'

export const NEW_ROBOT_OPTION = '__new__'
const NAME_MAX = 512

export interface AuthoredPartModalProps {
  projectId: string
  /** Existing physical_robot entities, listed by name. */
  robots: readonly Entity[]
  mode: SolMode
  /** Create a Physical Robot through the robot session; resolves its id or rejects. */
  createRobot: () => Promise<string>
  onCreated: (entity: Entity) => void
  onClose: () => void
}

const LABEL_STYLE = {
  display: 'block',
  marginTop: 12,
  fontSize: 11,
  color: 'var(--mut)'
} as const
const CONTROL_STYLE = { ...MODAL_INPUT_STYLE, marginTop: 4 } as const

/** Numbers parse as numbers; blank fields are omitted. Pure. */
export function authoredSpecs(
  category: RobotCategory,
  values: Record<string, string>
): NonNullable<PartIn['specs']> {
  const specs: Record<string, string | number> = {}
  for (const field of HARDWARE_SPEC_FIELDS[category]) {
    const raw = (values[field.key] ?? '').trim()
    if (!raw) continue
    if (field.kind === 'number') {
      const parsed = Number(raw)
      if (Number.isFinite(parsed)) specs[field.key] = parsed
    } else specs[field.key] = raw
  }
  return specs
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}

export function LabeledSelect<T extends string>({
  label,
  value,
  options,
  onChange
}: {
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
}): React.JSX.Element {
  return (
    <label style={LABEL_STYLE}>
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        style={CONTROL_STYLE}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function SpecFields({
  category,
  values,
  onChange
}: {
  category: RobotCategory
  values: Record<string, string>
  onChange: (values: Record<string, string>) => void
}): React.JSX.Element {
  return (
    <>
      {HARDWARE_SPEC_FIELDS[category].map((field) => (
        <label key={field.key} style={LABEL_STYLE}>
          {field.label}
          <input
            type={field.kind === 'number' ? 'number' : 'text'}
            inputMode={field.kind === 'number' ? 'decimal' : undefined}
            step={field.kind === 'number' ? 'any' : undefined}
            value={values[field.key] ?? ''}
            placeholder={field.placeholder}
            onChange={(event) => onChange({ ...values, [field.key]: event.target.value })}
            style={CONTROL_STYLE}
          />
        </label>
      ))}
    </>
  )
}

export function AuthoredPartModal({
  projectId,
  robots,
  mode,
  createRobot,
  onCreated,
  onClose
}: AuthoredPartModalProps): React.JSX.Element {
  const [name, setName] = useState('')
  const [robotId, setRobotId] = useState(robots[0]?.id ?? NEW_ROBOT_OPTION)
  const [category, setCategory] = useState<RobotCategory>('sensors')
  const [lifecycle, setLifecycle] = useState<LifecycleState>('planned')
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const trimmed = name.trim()
  const canCreate = trimmed.length > 0 && trimmed.length <= NAME_MAX && !busy

  const submit = async (): Promise<void> => {
    if (!canCreate) return
    setBusy(true)
    setError(null)
    try {
      const target = robotId === NEW_ROBOT_OPTION ? await createRobot() : robotId
      const input: PartIn = {
        name: trimmed,
        category,
        specs: authoredSpecs(category, values),
        lifecycle
      }
      const created = await createHardwarePart(projectId, target, input)
      onCreated(created.entity)
      onClose()
    } catch (failure) {
      setError(messageOf(failure))
      setBusy(false)
    }
  }

  return (
    <ModalShell onClose={onClose} width={440}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Author a part</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        {HARDWARE_COPY.authored[mode]}
      </div>
      <label style={LABEL_STYLE}>
        Name
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Part name"
          maxLength={NAME_MAX}
          autoFocus
          style={CONTROL_STYLE}
        />
      </label>
      <LabeledSelect
        label="Robot"
        value={robotId}
        onChange={setRobotId}
        options={[
          ...robots.map((robot) => ({ value: robot.id, label: robot.name })),
          { value: NEW_ROBOT_OPTION, label: 'New Physical Robot' }
        ]}
      />
      <LabeledSelect
        label="Category"
        value={category}
        onChange={(next) => {
          setCategory(next)
          setValues({})
        }}
        options={ROBOT_CATEGORIES.map((id) => ({ value: id, label: ROBOT_CATEGORY_LABELS[id] }))}
      />
      <SpecFields category={category} values={values} onChange={setValues} />
      <LabeledSelect
        label="Lifecycle"
        value={lifecycle}
        onChange={setLifecycle}
        options={LIFECYCLE_STATES.map((state) => ({ value: state, label: state }))}
      />
      {busy && <p role="status">Creating part…</p>}
      {error && (
        <p role="alert" style={{ color: 'var(--err)', fontSize: 11.5 }}>
          {error}
        </p>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" disabled={!canCreate} onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Create'}
        </Button>
      </div>
    </ModalShell>
  )
}
