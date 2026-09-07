// The proposal half of the Detected flow (docs/wireflows/hardware-onboarding.md
// Flow 1 steps 2–6): summary, driver, disambiguation, target, the
// RecognitionPanel rows with a category each, and Confirm. Nothing is sent
// before Confirm; only accepted/edited rows travel (ADR-012).
import { useId, useMemo, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  confirmDetected,
  type ConfirmIn,
  type ConfirmOut,
  type ConfirmTarget,
  type ProposalOut,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { RecognitionPanel } from '../../../widgets/livebench/recognition/RecognitionPanel'
import type { Decision } from '../../../widgets/livebench/recognition/proposals.types'
import { MODAL_INPUT_STYLE } from '../../workspace/modals'
import { LabeledSelect, NEW_ROBOT_OPTION } from './AuthoredPartModal'
import { acceptedRows, hardwareErrorText, robotIdFromMessage, toMappingProposal } from './detected'
import { HARDWARE_COPY } from './hardware.constants'

export interface ProposalViewProps {
  projectId: string
  proposal: ProposalOut
  robots: readonly Entity[]
  mode: SolMode
  onCreated: (entity: Entity) => void
  onClose: () => void
}

type Outcome =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'done'; result: ConfirmOut }
  | { kind: 'error'; message: string }
  | { kind: 'conflict'; message: string; robotId: string | null }

const MUTED = { fontSize: 12, color: 'var(--mut)', margin: '8px 0 0' } as const
const MONO = { fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--mut)' } as const
const CELL_SELECT = {
  ...MODAL_INPUT_STYLE,
  marginTop: 0,
  padding: '4px 6px',
  fontSize: 11.5,
  width: 'auto'
} as const
const PICK_ROBOT_HINT = 'Pick the robot to add to, then Confirm again.'

function sessionText(result: ConfirmOut): string {
  if (result.session_id) return 'streaming'
  return result.session_error ?? 'no session started'
}

function ConfirmedView({
  result,
  onClose
}: {
  result: ConfirmOut
  onClose: () => void
}): React.JSX.Element {
  return (
    <>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Robot confirmed</div>
      <p role="status" style={{ ...MUTED, color: 'var(--tx)' }}>
        {result.robot.name} — {result.part_ids.length} parts, {sessionText(result)}
      </p>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
        <Button kind="primary" size="sm" onClick={onClose}>
          Done
        </Button>
      </div>
    </>
  )
}

function DisambiguationGroup({
  proposal,
  value,
  onChange
}: {
  proposal: ProposalOut
  value: string | null
  onChange: (configId: string) => void
}): React.JSX.Element | null {
  const questionId = useId()
  const question = proposal.disambiguation
  if (question === null) return null
  return (
    <div role="radiogroup" aria-labelledby={questionId} style={{ marginTop: 12 }}>
      <div id={questionId} style={{ fontSize: 12, color: 'var(--tx)' }}>
        {question.question}
      </div>
      {question.options.map((configId) => {
        const match = proposal.repo_matches.find((m) => m.config_id === configId)
        return (
          <label key={configId} style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
            <input
              type="radio"
              name="repo-config"
              value={configId}
              checked={value === configId}
              onChange={() => onChange(configId)}
            />{' '}
            {match ? `${match.label} — ${match.source}` : configId}
          </label>
        )
      })}
    </div>
  )
}

function OutcomeLine({
  outcome,
  onRetarget
}: {
  outcome: Outcome
  onRetarget: (robotId: string | null) => void
}): React.JSX.Element | null {
  if (outcome.kind === 'busy') return <p role="status">Confirming…</p>
  if (outcome.kind !== 'error' && outcome.kind !== 'conflict') return null
  return (
    <p role="alert" style={{ color: 'var(--err)', fontSize: 11.5 }}>
      {outcome.message}
      {outcome.kind === 'conflict' && (
        <>
          {' '}
          <Button kind="soft" size="sm" onClick={() => onRetarget(outcome.robotId)}>
            Add to that robot instead
          </Button>
        </>
      )}
    </p>
  )
}

export function ProposalView({
  projectId,
  proposal,
  robots,
  mode,
  onCreated,
  onClose
}: ProposalViewProps): React.JSX.Element {
  const rows = useMemo(() => proposal.rows.map(toMappingProposal), [proposal])
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [categories, setCategories] = useState<Record<string, RobotCategory>>({})
  const [repoConfigId, setRepoConfigId] = useState<string | null>(null)
  const [targetId, setTargetId] = useState(NEW_ROBOT_OPTION)
  const [name, setName] = useState(proposal.summary)
  const [outcome, setOutcome] = useState<Outcome>({ kind: 'idle' })

  const accepted = acceptedRows(proposal.rows, decisions, categories)
  const needsChoice = proposal.disambiguation !== null && repoConfigId === null
  const canConfirm = accepted.length > 0 && !needsChoice && outcome.kind !== 'busy'

  const submit = async (target: ConfirmTarget): Promise<void> => {
    const body: ConfirmIn = {
      target,
      accepted,
      ...(repoConfigId ? { repo_config_id: repoConfigId } : {}),
      start_session: true,
      window_seconds: 1
    }
    setOutcome({ kind: 'busy' })
    try {
      const result = await confirmDetected(projectId, proposal.device_ref, body)
      setOutcome({ kind: 'done', result })
      onCreated(result.robot)
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        setOutcome({
          kind: 'conflict',
          message: failure.message,
          robotId: robotIdFromMessage(failure.message)
        })
      } else setOutcome({ kind: 'error', message: hardwareErrorText(failure) })
    }
  }

  const confirm = (): void => {
    const trimmed = name.trim()
    void submit(
      targetId === NEW_ROBOT_OPTION
        ? { kind: 'new', ...(trimmed ? { name: trimmed } : {}) }
        : { kind: 'existing', robot_id: targetId }
    )
  }

  const retarget = (robotId: string | null): void => {
    if (robotId) {
      void submit({ kind: 'existing', robot_id: robotId })
      return
    }
    setTargetId(robots[0]?.id ?? NEW_ROBOT_OPTION)
    setOutcome({ kind: 'error', message: PICK_ROBOT_HINT })
  }

  if (outcome.kind === 'done') return <ConfirmedView result={outcome.result} onClose={onClose} />

  return (
    <>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{proposal.summary}</div>
      <p style={MUTED}>{HARDWARE_COPY.proposal[mode]}</p>
      <div style={{ ...MONO, marginTop: 8 }}>
        {proposal.driver_id ?? 'no driver'} · {JSON.stringify(proposal.params)}
      </div>
      <p style={MUTED}>Link this project&apos;s folder on this machine to read your repo config</p>
      <DisambiguationGroup proposal={proposal} value={repoConfigId} onChange={setRepoConfigId} />
      <div style={{ marginTop: 12, overflowX: 'auto' }}>
        <RecognitionPanel
          proposals={rows}
          onDecision={(id, decision) => setDecisions((prev) => ({ ...prev, [id]: decision }))}
          renderRowExtra={(row) => (
            <select
              aria-label={`Category for ${row.subject}`}
              value={categories[row.id] ?? 'actuators'}
              onChange={(event) =>
                setCategories((prev) => ({
                  ...prev,
                  [row.id]: event.target.value as RobotCategory
                }))
              }
              style={CELL_SELECT}
            >
              {ROBOT_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {ROBOT_CATEGORY_LABELS[category]}
                </option>
              ))}
            </select>
          )}
        />
      </div>
      <LabeledSelect
        label="Target"
        value={targetId}
        onChange={setTargetId}
        options={[
          { value: NEW_ROBOT_OPTION, label: 'Add as new Physical Robot' },
          ...robots.map((robot) => ({ value: robot.id, label: `Add to ${robot.name}` }))
        ]}
      />
      {targetId === NEW_ROBOT_OPTION && (
        <label style={{ display: 'block', marginTop: 12, fontSize: 11, color: 'var(--mut)' }}>
          Robot name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={512}
            style={{ ...MODAL_INPUT_STYLE, marginTop: 4 }}
          />
        </label>
      )}
      <OutcomeLine outcome={outcome} onRetarget={retarget} />
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" disabled={!canConfirm} onClick={confirm}>
          {outcome.kind === 'busy' ? <Spinner size={11} color="var(--acc-ink)" /> : 'Confirm'}
        </Button>
      </div>
    </>
  )
}
