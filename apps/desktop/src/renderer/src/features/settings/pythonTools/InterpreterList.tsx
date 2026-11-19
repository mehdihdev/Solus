// SOLUSDEV-329 — the interpreter rows of Settings › Python for local tools:
// supported candidates first (path in mono, version), the managed option,
// then unsupported ones dimmed with the reason. All CLI strings render as text.
import { useId } from 'react'
import type { Candidate, ChoiceView } from '../../../../../main/mcpRuntime/channels'
import { MANAGED_OPTION, candidateReason } from './pythonToolsCopy'

export interface InterpreterListProps {
  candidates: readonly Candidate[]
  choice: ChoiceView | null
  disabled: boolean
  onCandidate: (candidate: Candidate) => void
  onManaged: () => void
}

const MANAGED_VALUE = 'managed'

function selectedValue(candidates: readonly Candidate[], choice: ChoiceView | null): string | null {
  if (choice?.mode === 'managed') return MANAGED_VALUE
  if (choice?.mode === 'path') return choice.path
  return candidates.find((c) => c.supported && c.source !== 'managed')?.path ?? null
}

function Option({
  name,
  value,
  checked,
  disabled,
  onSelect,
  children
}: {
  name: string
  value: string
  checked: boolean
  disabled: boolean
  onSelect: () => void
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <label style={{ ...OPTION, opacity: disabled ? 0.55 : 1 }}>
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={onSelect}
      />
      {children}
    </label>
  )
}

export function InterpreterList(props: InterpreterListProps): React.JSX.Element {
  const name = useId()
  const selected = selectedValue(props.candidates, props.choice)
  const usable = props.candidates.filter((c) => c.supported && c.source !== 'managed')
  const unusable = props.candidates.filter((c) => !c.supported)
  return (
    <div role="radiogroup" aria-label="Python interpreter" style={LIST}>
      {usable.map((c) => (
        <Option
          key={c.path}
          name={name}
          value={c.path}
          checked={selected === c.path}
          disabled={props.disabled}
          onSelect={() => props.onCandidate(c)}
        >
          <span style={PATH}>{c.path}</span>
          <span style={VERSION}>{c.version}</span>
        </Option>
      ))}
      <Option
        name={name}
        value={MANAGED_VALUE}
        checked={selected === MANAGED_VALUE}
        disabled={props.disabled}
        onSelect={props.onManaged}
      >
        <span>{MANAGED_OPTION}</span>
      </Option>
      {unusable.map((c) => (
        <Option
          key={c.path}
          name={name}
          value={c.path}
          checked={false}
          disabled
          onSelect={() => undefined}
        >
          <span style={PATH}>{c.path}</span>
          <span style={VERSION}>{candidateReason(c.reason, c.version)}</span>
        </Option>
      ))}
    </div>
  )
}

const LIST: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6 }
const OPTION: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  fontSize: 12.5,
  flexWrap: 'wrap'
}
const PATH: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  overflowWrap: 'anywhere'
}
const VERSION: React.CSSProperties = { color: 'var(--mut)', fontSize: 11.5 }
