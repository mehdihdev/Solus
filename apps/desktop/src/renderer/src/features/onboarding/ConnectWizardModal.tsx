// The connect wizard (SOLUSDEV-165): one modal that walks a user through
// connecting ANY connector, replacing the inline in-tile flow. Everything it
// renders is derived from the connector's DECLARED shape (connectSteps.ts) and
// the LIVE ConnectionState the flow engines emit — no provider ids, no
// fabricated copy. Layout: Solus↔tool link animation, dynamic step rail,
// SOL-mode instruction (ADR-016), and one action area that hosts whatever the
// current step needs.
import { useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { IntegrationAccessModes, SelectableItem } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import { ModalShell } from '../workspace/modals'
import { SelectionPicker, PICKER_FIELD_STYLE } from './SelectionPicker'
import { stepInstruction, wizardPosition, wizardSteps, type WizardStep } from './connectSteps'
import type { CatalogEntry } from './integrationCatalog'
import { integrationLogo } from './integrationLogos'
import type { ConnectionState } from './onboardingStore'

/** Committed netlist exports a user can pick (KiCad XML netlist first). */
export const EXPORT_FILE_ACCEPT = '.xml,.net'

const LINK_DOTS = 6

export interface ConnectWizardModalProps {
  entry: CatalogEntry
  /** Live flow state from the store; absent until the flow starts. */
  state?: ConnectionState
  /** Start (or retry) the flow — OAuth path. */
  onBegin: () => void
  /** Start the flow with the picked committed export — file path. */
  onPickFile: (file: { fileName: string; content: string }) => void
  /** Resolve the picker step (null cancels). */
  onSelect: (items: SelectableItem[] | null) => void
  /** Resolve the details-form step. */
  onSubmitConfig: (values: Record<string, string>) => void
  /** Resolve the grant-choice step (null cancels). */
  onChooseAccess: (mode: string | null) => void
  /** Close the wizard. Mid-flight, the caller treats this as cancel. */
  onClose: () => void
}

/** A config field whose VALUE should never be shown while typed. The registry
 * names the fields; anything credential-shaped gets a masked input. */
export function isSecretField(field: string): boolean {
  return /(key|secret|token|license|password)/i.test(field)
}

/** `document_id` → `Document id`. */
function fieldLabel(field: string): string {
  const words = field.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function EndpointMark({
  label,
  busy,
  children
}: {
  label: string
  busy: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <span
      aria-label={label}
      className={busy ? 'cw-mark-busy' : undefined}
      style={{
        width: 52,
        height: 52,
        borderRadius: 8,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        flexShrink: 0
      }}
    >
      {children}
    </span>
  )
}

/** Solus box — travelling dots — integration logo (or letter mark). */
function LinkHeader({
  entry,
  status
}: {
  entry: CatalogEntry
  status: 'idle' | 'busy' | 'done' | 'error'
}): React.JSX.Element {
  const logo = integrationLogo(entry.id)
  const dotColor =
    status === 'done' ? 'var(--ok)' : status === 'error' ? 'var(--err)' : 'var(--acc)'
  return (
    <div
      aria-hidden
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 14,
        padding: '10px 0 4px'
      }}
    >
      <EndpointMark label="Solus" busy={status === 'busy'}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 600 }}>S</span>
      </EndpointMark>
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        {Array.from({ length: LINK_DOTS }, (_, i) => (
          <span
            key={i}
            className={status === 'busy' ? 'cw-dot-busy' : undefined}
            style={{
              width: 6,
              height: 6,
              borderRadius: 99,
              background: dotColor,
              opacity: status === 'busy' ? undefined : status === 'idle' ? 0.3 : 0.9,
              animationDelay: `${i * 0.12}s`
            }}
          />
        ))}
      </span>
      <EndpointMark label={entry.name} busy={status === 'busy'}>
        {logo ? (
          <img src={logo} alt="" style={{ width: 34, height: 34, objectFit: 'contain' }} />
        ) : (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 500 }}>
            {entry.mark}
          </span>
        )}
      </EndpointMark>
    </div>
  )
}

function StepRail({
  steps,
  stepIndex,
  status
}: {
  steps: readonly WizardStep[]
  stepIndex: number
  status: 'idle' | 'busy' | 'done' | 'error'
}): React.JSX.Element {
  return (
    <div
      aria-label="Connect steps"
      style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 6,
        marginTop: 14,
        flexWrap: 'wrap'
      }}
    >
      {steps.map((step, i) => {
        const isCurrent = status !== 'done' && i === stepIndex
        const isDone = status === 'done' || i < stepIndex
        return (
          <span
            key={step.id}
            data-step
            aria-current={isCurrent ? 'step' : undefined}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 99,
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              border: '1px solid',
              borderColor: isCurrent ? 'var(--acc)' : 'var(--bd)',
              color: isDone ? 'var(--ok)' : isCurrent ? 'var(--tx)' : 'var(--mut)',
              background: isCurrent ? 'color-mix(in srgb, var(--acc) 10%, transparent)' : 'none',
              transition: 'border-color 0.2s, color 0.2s, background 0.2s'
            }}
          >
            {isDone && <Icons.check size={11} />}
            {step.title}
          </span>
        )
      })}
    </div>
  )
}

/** The generic connector-details form (one input per live config field). */
function ConfigForm({
  fields,
  onSubmitConfig
}: {
  fields: readonly string[]
  onSubmitConfig: (values: Record<string, string>) => void
}): React.JSX.Element {
  const [values, setValues] = useState<Record<string, string>>({})
  const complete = fields.every((field) => values[field]?.trim())
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {fields.map((field) => (
        <input
          key={field}
          aria-label={fieldLabel(field)}
          placeholder={fieldLabel(field)}
          type={isSecretField(field) ? 'password' : 'text'}
          value={values[field] ?? ''}
          onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
          style={PICKER_FIELD_STYLE}
        />
      ))}
      <Button kind="primary" size="sm" disabled={!complete} onClick={() => onSubmitConfig(values)}>
        Continue
      </Button>
    </div>
  )
}

/** The connect-time grant choice; descriptions shown, connector's own default. */
function AccessPicker({
  accessModes,
  onChooseAccess
}: {
  accessModes: IntegrationAccessModes
  onChooseAccess: (mode: string | null) => void
}): React.JSX.Element {
  const [chosen, setChosen] = useState(accessModes.default)
  return (
    <div style={{ display: 'grid', gap: 8, textAlign: 'left' }}>
      {accessModes.modes.map((mode) => (
        <label
          key={mode.id}
          style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer' }}
        >
          <input
            type="radio"
            name="solus-access-mode"
            aria-label={mode.label}
            checked={chosen === mode.id}
            onChange={() => setChosen(mode.id)}
            style={{ marginTop: 3 }}
          />
          <span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>{mode.label}</span>
            <span style={{ display: 'block', fontSize: 11, color: 'var(--mut)' }}>
              {mode.description}
            </span>
          </span>
        </label>
      ))}
      <Button kind="primary" size="sm" onClick={() => onChooseAccess(chosen)}>
        Continue
      </Button>
    </div>
  )
}

/** The step-zero call to action: pick the export file, or start the OAuth flow. */
function IdleAction({
  entry,
  onBegin,
  onPickFile
}: Pick<ConnectWizardModalProps, 'entry' | 'onBegin' | 'onPickFile'>): React.JSX.Element {
  const fileInput = useRef<HTMLInputElement | null>(null)

  const pickFile = async (input: HTMLInputElement): Promise<void> => {
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    onPickFile({ fileName: file.name, content: await file.text() })
  }

  if (entry.mode !== 'export-file') {
    return (
      <Button kind="primary" size="sm" onClick={onBegin}>
        Connect {entry.name}
      </Button>
    )
  }
  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept={EXPORT_FILE_ACCEPT}
        aria-label="Choose a committed netlist export"
        style={{ display: 'none' }}
        onChange={(e) => void pickFile(e.currentTarget)}
      />
      <Button kind="primary" size="sm" onClick={() => fileInput.current?.click()}>
        <Icons.file size={12} /> Choose export file
      </Button>
    </>
  )
}

/** Whatever input the busy flow is waiting on, or its live progress line. */
function BusyAction({
  state,
  onSelect,
  onSubmitConfig,
  onChooseAccess
}: Pick<
  ConnectWizardModalProps,
  'state' | 'onSelect' | 'onSubmitConfig' | 'onChooseAccess'
>): React.JSX.Element {
  if (state?.phase !== 'busy') return <Spinner />
  if (state.accessModes) {
    return <AccessPicker accessModes={state.accessModes} onChooseAccess={onChooseAccess} />
  }
  if (state.selectable && state.selectable.length > 0) {
    return (
      <SelectionPicker items={state.selectable} mode={state.selectionMode} onSelect={onSelect} />
    )
  }
  if (state.configFields && state.configFields.length > 0) {
    return <ConfigForm fields={state.configFields} onSubmitConfig={onSubmitConfig} />
  }
  return (
    <span
      style={{
        display: 'inline-flex',
        gap: 8,
        alignItems: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--acc)'
      }}
    >
      <Spinner size={11} /> {state.label ?? 'Connecting…'}
    </span>
  )
}

/** Whatever the current moment needs from the user. */
function ActionArea(
  props: ConnectWizardModalProps & { status: 'idle' | 'busy' | 'done' | 'error' }
): React.JSX.Element {
  if (props.status === 'done') {
    return (
      <Button kind="primary" size="sm" onClick={props.onClose}>
        Done
      </Button>
    )
  }
  if (props.status === 'error') {
    return (
      <Button kind="primary" size="sm" onClick={props.onBegin}>
        Retry
      </Button>
    )
  }
  if (props.status === 'idle') return <IdleAction {...props} />
  return <BusyAction {...props} />
}

/** Headline + instruction for the current moment. Live copy from the flow
 * (result, error) wins; step copy is SOL-mode aware (ADR-016). */
function wizardCopy(
  status: 'idle' | 'busy' | 'done' | 'error',
  step: WizardStep,
  entry: CatalogEntry,
  state: ConnectionState | undefined,
  solMode: 'Guide' | 'Expert'
): { headline: string; instruction: string } {
  if (status === 'done') {
    const result = state?.phase === 'done' ? state.result : undefined
    return { headline: `${entry.name} connected`, instruction: result ?? 'Connected' }
  }
  if (status === 'error') {
    const error = state?.phase === 'error' ? state.error : 'Something went wrong.'
    return { headline: `Couldn't connect ${entry.name}`, instruction: error }
  }
  return {
    headline: step.title,
    instruction: stepInstruction(
      step,
      { name: entry.name, selectionLabel: entry.selection?.label },
      solMode
    )
  }
}

function CloseButton({ onClose }: { onClose: () => void }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
      <button
        aria-label="Close"
        onClick={onClose}
        className="interactive"
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--mut)',
          padding: 4,
          borderRadius: 4,
          lineHeight: 0
        }}
      >
        <Icons.x size={14} />
      </button>
    </div>
  )
}

export function ConnectWizardModal(props: ConnectWizardModalProps): React.JSX.Element {
  const { entry, state, onClose } = props
  const solMode = useSettingsStore((s) => s.solMode)
  const steps = wizardSteps(entry)
  const { status, stepIndex } = wizardPosition(steps, state)
  const step = steps[Math.min(stepIndex, steps.length - 1)]
  const { headline, instruction } = wizardCopy(status, step, entry, state, solMode)

  return (
    <ModalShell onClose={onClose} width={520}>
      <div role="dialog" aria-modal="true" aria-label={`Connect ${entry.name}`} className="cw-pop">
        <CloseButton onClose={onClose} />
        <LinkHeader entry={entry} status={status} />
        <StepRail steps={steps} stepIndex={stepIndex} status={status} />
        <div
          key={`${status}-${step.id}`}
          className="cw-step-in"
          style={{ textAlign: 'center', marginTop: 18 }}
        >
          <div style={{ fontSize: 15, fontWeight: 600 }}>{headline}</div>
          <div
            data-testid="cw-instruction"
            style={{
              fontSize: 12,
              lineHeight: 1.55,
              marginTop: 6,
              color: status === 'error' ? 'var(--err)' : 'var(--mut)',
              minHeight: 18
            }}
          >
            {instruction}
          </div>
          <div
            style={{
              marginTop: 16,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 8
            }}
          >
            <div style={{ width: 320, maxWidth: '100%' }}>
              <ActionArea {...props} status={status} />
            </div>
          </div>
        </div>
      </div>
    </ModalShell>
  )
}
