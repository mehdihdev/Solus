// One device, one sentence, one question (SOLUSDEV-250 P3, ADR-012): the card
// proposes what the wire said and asks the single thing only the user knows.
// Nothing is sent before Add; nothing auto-accepts. Connection state does not
// claim telemetry has arrived.
import { useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import type { ConfirmOut, HardwareSuggestion, ProposalOut } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { markDeviceRendered } from '../../../lib/perf/marks'
import {
  cardGlyph,
  cardQuestion,
  cardSentence,
  conflictText,
  evidenceNotes,
  type CardQuestion,
  type DeviceCardState
} from './deviceCard'
import type { ConfirmInput } from './useDeviceProposals'
import './hardware.css'

export interface DeviceCardProps {
  state: DeviceCardState
  robots: readonly Entity[]
  mode: SolMode
  compact?: boolean
  onConfirm: (input: ConfirmInput) => void
  onAccept: (suggestion: HardwareSuggestion) => void
  onDismiss: () => void
  onRetry: () => void
}

const SILENT_TEXT = 'Nothing answered yet — is it powered and free?'
const MAX_NAME = 512

function doneText(result: ConfirmOut | null): string {
  if (!result) return 'Added'
  const connection = result.robot.properties?.connection
  if (
    typeof connection === 'object' &&
    connection !== null &&
    'status' in connection &&
    connection.status === 'connecting'
  ) {
    return 'Added · connecting…'
  }
  if (result.session_id) return 'Added · connected'
  return `Added · ${result.session_error ?? 'no session started'}`
}

/** The single repo match's label is OFFERED as the placeholder, never filled in. */
function namePlaceholder(proposal: ProposalOut): string {
  return proposal.repo_matches.length === 1 ? proposal.repo_matches[0].label : 'Name this robot'
}

/** The robot a suggestion names, by name only — an id is never shown. */
function suggestedName(robots: readonly Entity[], suggestion: HardwareSuggestion): string {
  return (
    robots.find((robot) => robot.id === suggestion.candidate_robot_id)?.name ??
    'a robot you imported'
  )
}

export function DeviceCard(props: DeviceCardProps): React.JSX.Element {
  const { state, mode, compact } = props
  const sentence = cardSentence(state.device, state.proposal, state.status)
  const notes = mode === 'Guide' && state.proposal ? evidenceNotes(state.proposal) : ''
  // Once per device ref: the rail and Add › Hardware both mount this card.
  useEffect(() => {
    markDeviceRendered(state.ref)
  }, [state.ref])
  return (
    <article className={compact ? 'device-card device-card-compact' : 'device-card'}>
      <p className="device-card-sentence">
        <span className="device-card-glyph" aria-hidden="true">
          {cardGlyph(state.proposal)}
        </span>
        <span>{sentence}</span>
        {state.status === 'proposing' && <Spinner size={11} />}
      </p>
      {notes && <p className="device-card-note">{notes}</p>}
      <CardBody {...props} />
    </article>
  )
}

/** Every card that is not mid-flight can be put away for the session. */
function NotNow({ onDismiss }: Pick<DeviceCardProps, 'onDismiss'>): React.JSX.Element {
  return (
    <Button kind="bare" size="sm" onClick={onDismiss}>
      Not now
    </Button>
  )
}

function CardBody(props: DeviceCardProps): React.JSX.Element | null {
  const { state, onRetry, onDismiss } = props
  if (state.device.ambiguous)
    return (
      <p className="device-card-row device-card-note">
        <span>{state.error}</span>
        <NotNow onDismiss={onDismiss} />
      </p>
    )
  if (state.status === 'proposing') return null
  if (state.status === 'done')
    return (
      <p role="status" className="device-card-done">
        {doneText(state.result)}
      </p>
    )
  if (state.status === 'silent' || (state.status === 'failed' && !state.proposal))
    return (
      <p role={state.status === 'failed' ? 'alert' : undefined} className="device-card-row">
        <span>{state.status === 'silent' ? SILENT_TEXT : state.error}</span>
        <Button kind="soft" size="sm" onClick={onRetry}>
          Retry
        </Button>
        <NotNow onDismiss={onDismiss} />
      </p>
    )
  return <Question {...props} />
}

function Question({
  state,
  robots,
  onConfirm,
  onAccept,
  onDismiss
}: DeviceCardProps): React.JSX.Element | null {
  const [choice, setChoice] = useState<string | null>(null)
  const proposal = state.proposal
  if (!proposal) return null
  const question = cardQuestion(proposal)
  const busy = state.status === 'confirming'
  return (
    <div className="device-card-question">
      {state.status === 'failed' && (
        <p role="alert" className="device-card-row device-card-error">
          <span>{conflictText(state.error ?? '', robots)}</span>
          {state.conflictRobotId && (
            <Button
              kind="soft"
              size="sm"
              onClick={() =>
                onConfirm({ target: { kind: 'existing', robot_id: state.conflictRobotId ?? '' } })
              }
            >
              Add to that robot instead
            </Button>
          )}
        </p>
      )}
      {question.kind === 'choose' && (
        <ChooseRow question={question} choice={choice} busy={busy} onChoose={setChoice} />
      )}
      {(question.kind !== 'choose' || choice !== null) && (
        <NameRow
          proposal={proposal}
          robots={robots}
          busy={busy}
          repoConfigId={choice}
          suggestion={question.kind === 'suggest' ? question.suggestion : null}
          onConfirm={onConfirm}
          onAccept={onAccept}
        />
      )}
      <Button kind="bare" size="sm" disabled={busy} onClick={onDismiss}>
        Not now
      </Button>
    </div>
  )
}

function ChooseRow({
  question,
  choice,
  busy,
  onChoose
}: {
  question: Extract<CardQuestion, { kind: 'choose' }>
  choice: string | null
  busy: boolean
  onChoose: (configId: string) => void
}): React.JSX.Element {
  return (
    <div className="device-card-row" role="group" aria-label={question.question}>
      <span>{question.question}</span>
      {question.options.map((option) => (
        <Button
          key={option.configId}
          kind={choice === option.configId ? 'primary' : 'soft'}
          size="sm"
          aria-pressed={choice === option.configId}
          disabled={busy}
          onClick={() => onChoose(option.configId)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  )
}

function NameRow({
  proposal,
  robots,
  busy,
  repoConfigId,
  suggestion,
  onConfirm,
  onAccept
}: {
  proposal: ProposalOut
  robots: readonly Entity[]
  busy: boolean
  repoConfigId: string | null
  suggestion: HardwareSuggestion | null
  onConfirm: (input: ConfirmInput) => void
  onAccept: (suggestion: HardwareSuggestion) => void
}): React.JSX.Element {
  const [name, setName] = useState('')
  const [robotId, setRobotId] = useState('')
  const trimmed = name.trim()
  const ready = robotId !== '' || (trimmed.length > 0 && trimmed.length <= MAX_NAME)
  const add = (): void =>
    onConfirm({
      target: robotId ? { kind: 'existing', robot_id: robotId } : { kind: 'new', name: trimmed },
      ...(repoConfigId ? { repoConfigId } : {})
    })
  return (
    <div className="device-card-row">
      <span>What is this?</span>
      <input
        aria-label="Robot name"
        value={name}
        placeholder={namePlaceholder(proposal)}
        maxLength={MAX_NAME}
        disabled={busy || robotId !== ''}
        onChange={(event) => setName(event.target.value)}
      />
      {robots.length > 0 && (
        <select
          aria-label="Part of"
          value={robotId}
          disabled={busy}
          onChange={(event) => setRobotId(event.target.value)}
        >
          <option value="">New robot</option>
          {robots.map((robot) => (
            <option key={robot.id} value={robot.id}>
              {robot.name}
            </option>
          ))}
        </select>
      )}
      {suggestion && (
        <Button kind="soft" size="sm" disabled={busy} onClick={() => onAccept(suggestion)}>
          It’s {suggestedName(robots, suggestion)}
        </Button>
      )}
      {busy ? (
        <Spinner size={11} />
      ) : (
        <Button kind="primary" size="sm" disabled={!ready} onClick={add}>
          Add
        </Button>
      )}
    </div>
  )
}
