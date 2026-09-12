// Describe something new (SOLUSDEV-250 P3, docs/wireflows/hardware-onboarding.md Flow 5):
// one field. The category is guessed from the name and said to be a guess; specs come
// later. With no robot yet, the described thing IS the robot — a name is enough (ADR-012).
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import { Spinner } from '../../../components/ui/Spinner'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  createHardwarePart,
  type RobotCategory
} from '../../../lib/api/hardware'
import { createPhysicalRobot } from '../../../lib/api/physicalRobots'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { categoryFromName } from './categoryFromName'
import { hardwareErrorText } from './detected'
import { FIELD_CONTROL_STYLE, FIELD_LABEL_STYLE, HARDWARE_COPY } from './hardware.constants'
import { LabeledSelect } from './LabeledSelect'

export interface DescribeNewProps {
  projectId: string
  mode: SolMode
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  disabled: boolean
}

const NAME_MAX = 512
const BODY_STYLE = {
  fontSize: 12,
  color: 'var(--mut)',
  margin: '8px 0 0',
  lineHeight: 1.5
} as const
const CATEGORY_OPTIONS = ROBOT_CATEGORIES.map((id) => ({
  value: id,
  label: ROBOT_CATEGORY_LABELS[id]
}))
const IS_ROBOT = 'No robot yet — this becomes the robot.'

interface Draft {
  name: string
  trimmed: string
  category: RobotCategory
  guessed: boolean
  robotId: string | null
  busy: boolean
  error: string | null
  canAdd: boolean
  setName: (name: string) => void
  setCategory: (category: RobotCategory) => void
  setRobot: (id: string) => void
  submit: () => void
}

function useDraft(
  projectId: string,
  robots: readonly Entity[],
  onCreated: (entity: Entity) => void,
  disabled: boolean
): Draft {
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<RobotCategory | null>(null)
  const [robotChoice, setRobotChoice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const trimmed = name.trim()
  const category = chosen ?? categoryFromName(trimmed).category
  const robotId = robotChoice ?? robots[0]?.id ?? null
  const canAdd = trimmed.length > 0 && trimmed.length <= NAME_MAX && !busy && !disabled

  const create = (): Promise<Entity> =>
    robotId
      ? createHardwarePart(projectId, robotId, {
          name: trimmed,
          category,
          specs: {},
          lifecycle: 'planned'
        }).then((out) => out.entity)
      : createPhysicalRobot(projectId, undefined, trimmed)
  const submit = (): void => {
    setBusy(true)
    setError(null)
    create()
      .then((created) => {
        onCreated(created)
        setName('')
        setChosen(null)
      })
      .catch((failure: unknown) => setError(hardwareErrorText(failure)))
      .finally(() => setBusy(false))
  }
  return {
    name,
    trimmed,
    category,
    guessed: chosen === null && trimmed.length > 0,
    robotId,
    busy,
    error,
    canAdd,
    setName,
    setCategory: setChosen,
    setRobot: setRobotChoice,
    submit
  }
}

export function DescribeNew({
  projectId,
  mode,
  robots,
  onCreated,
  disabled
}: DescribeNewProps): React.JSX.Element {
  const draft = useDraft(projectId, robots, onCreated, disabled)
  return (
    <div>
      <label style={{ ...FIELD_LABEL_STYLE, marginTop: 0 }}>
        What is it?
        <input
          value={draft.name}
          disabled={disabled}
          maxLength={NAME_MAX}
          placeholder="A name is enough"
          onChange={(event) => draft.setName(event.target.value)}
          style={FIELD_CONTROL_STYLE}
        />
      </label>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <LabeledSelect
          label="Category"
          value={draft.category}
          onChange={draft.setCategory}
          disabled={disabled}
          options={CATEGORY_OPTIONS}
        />
        {draft.guessed && <Mono style={{ paddingBottom: 12 }}>guessed</Mono>}
        {draft.robotId && (
          <LabeledSelect
            label="Part of"
            value={draft.robotId}
            onChange={draft.setRobot}
            disabled={disabled}
            options={robots.map((robot) => ({ value: robot.id, label: robot.name }))}
          />
        )}
      </div>
      {!draft.robotId && draft.trimmed && <p style={BODY_STYLE}>{IS_ROBOT}</p>}
      <p style={BODY_STYLE}>{HARDWARE_COPY.describe[mode]}</p>
      {draft.error && (
        <p role="alert" style={{ ...BODY_STYLE, color: 'var(--err)' }}>
          {draft.error}
        </p>
      )}
      <div style={{ marginTop: 10 }}>
        <Button kind="primary" size="sm" disabled={!draft.canAdd} onClick={draft.submit}>
          {draft.busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Add'}
        </Button>
      </div>
    </div>
  )
}
