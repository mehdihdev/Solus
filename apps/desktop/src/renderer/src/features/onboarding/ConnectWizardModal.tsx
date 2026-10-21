// The connect wizard (SOLUSDEV-165): one modal that walks a user through
// connecting ANY connector, replacing the inline in-tile flow. Everything it
// renders is derived from the connector's DECLARED shape (connectSteps.ts) and
// the LIVE ConnectionState the flow engines emit — no provider ids, no
// fabricated copy. Layout: Solus↔tool link animation, dynamic step rail,
// SOL-mode instruction (ADR-016), and one action area that hosts whatever the
// current step needs.
import { useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { SolusLogo } from '../../components/ui/SolusLogo'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { IntegrationAccessModes, SelectableItem } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import { ModalShell } from '../workspace/modals'
import { SelectionPicker, PICKER_FIELD_STYLE } from './SelectionPicker'
import {
  stepInstruction,
  wizardPosition,
  wizardSteps,
  type WizardScope,
  type WizardStep
} from './connectSteps'
import type { CatalogEntry } from './integrationCatalog'
import { integrationLogo, logoClass } from './integrationLogos'
import { allowsMultipleFiles, exportFileAccept, exportFilePrompt } from './kicadFiles'
import type { ConnectionState } from './onboardingStore'
import { ACCOUNT_ENTRY_ID, SIGN_IN_ENTRY_ID } from './teamRepoSection'
import { stageTeamPick, useTeamPicker, type TeamPicker } from './useConnectWizard'

const LINK_DOTS = 6

export interface ConnectWizardModalProps {
  entry: CatalogEntry
  /** Live flow state from the store; absent until the flow starts. */
  state?: ConnectionState
  /** SOLUSDEV-241: `account` binds a provider account with no project (Home).
   *  Default `project`. */
  scope?: WizardScope
  /** SOLUSDEV-241: the linked account this connect will reuse, if any — the
   *  rail then skips the sign-in and the idle action says so. */
  linkedAccount?: { login: string | null } | null
  /** Start (or retry) the flow — OAuth path. */
  onBegin: () => void
  /** Start the flow with the user's picked committed export(s) — a netlist
   * and/or a board. The FILES are handed over unread — the wizard glue
   * validates their size first, so a multi-GB pick never gets slurped into
   * renderer memory. */
  onPickFiles: (files: File[]) => void
  /** Resolve the picker step (null cancels). */
  onSelect: (items: SelectableItem[] | null) => void
  onRefreshSelection?: () => Promise<SelectableItem[]>
  /** Resolve the details-form step. */
  onSubmitConfig: (values: Record<string, string>) => void
  /** Resolve the grant-choice step (null cancels). */
  onChooseAccess: (mode: string | null) => void
  /** Close the wizard. Mid-flight, the caller treats this as cancel. */
  onClose: () => void
}

/** A config field whose VALUE should never be shown while typed. The registry
 * names the fields; anything credential-shaped gets a masked input.
 *
 * The masking is on-screen hygiene ONLY: source `config` is stored and echoed
 * back by the API in plaintext, so connectors must NOT declare real secrets as
 * `config_fields` — credentials belong in the SecretStore (`secret_ref`).
 * Heuristic by design; a false positive only masks a harmless value. */
export function isSecretField(field: string): boolean {
  return /(key|secret|token|license|password|passphrase|credential)/i.test(field)
}

/** `document_id` → `Document id`. */
function fieldLabel(field: string): string {
  const words = field.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function EndpointMark({
  label,
  busy,
  plain = false,
  children
}: {
  label: string
  busy: boolean
  /** The child draws its own tile (the Solus logo): no second frame around it. */
  plain?: boolean
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
        background: plain ? 'transparent' : 'var(--sur2)',
        border: plain ? 'none' : '1px solid var(--bd)',
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

/** What the link header needs of an endpoint: enough to find a logo, else a mark. */
export type LinkEndpoint = Pick<CatalogEntry, 'id' | 'name' | 'mark'>

/** Solus box — travelling dots — integration logo (or letter mark). Exported
 *  so sibling dialogs (simulator start) share the wizard's visual language. */
export function LinkHeader({
  entry,
  status
}: {
  entry: LinkEndpoint
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
      <EndpointMark label="Solus" busy={status === 'busy'} plain>
        <SolusLogo size={52} />
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
          <img
            src={logo}
            alt=""
            className={logoClass(entry.id)}
            style={{ width: 34, height: 34, objectFit: 'contain' }}
          />
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

/** A local tool's one step: the registry's own guidance, verbatim, and Got it. */
function BridgeAction({
  entry,
  onClose
}: Pick<ConnectWizardModalProps, 'entry' | 'onClose'>): React.JSX.Element {
  const tool = entry.localTool
  return (
    <div style={{ display: 'grid', gap: 10, textAlign: 'left' }}>
      {tool && (
        <div style={{ fontSize: 12, lineHeight: 1.55 }} data-testid="cw-bridge-notice">
          {tool.connect_notice}
        </div>
      )}
      {tool && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>
          {tool.url_host}
        </div>
      )}
      <div style={{ textAlign: 'center' }}>
        <Button kind="primary" size="sm" onClick={onClose}>
          Got it
        </Button>
      </div>
    </div>
  )
}

/** The committed-export pick: a hidden file input behind a button, with the
 * provider's own prompt (KiCad takes a netlist and/or a board in one pick). */
function ExportFilePick({
  entry,
  onPickFiles
}: Pick<ConnectWizardModalProps, 'entry' | 'onPickFiles'>): React.JSX.Element {
  const fileInput = useRef<HTMLInputElement | null>(null)
  const prompt = exportFilePrompt(entry.id)

  const pickFiles = (input: HTMLInputElement): void => {
    const files = Array.from(input.files ?? [])
    input.value = ''
    if (files.length > 0) onPickFiles(files)
  }

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept={exportFileAccept(entry.id)}
        multiple={allowsMultipleFiles(entry.id)}
        aria-label={prompt.ariaLabel}
        style={{ display: 'none' }}
        onChange={(e) => pickFiles(e.currentTarget)}
      />
      <Button kind="primary" size="sm" onClick={() => fileInput.current?.click()}>
        <Icons.file size={12} /> {prompt.button}
      </Button>
      {prompt.hint && (
        <div style={{ marginTop: 8, fontSize: 11, lineHeight: 1.5, color: 'var(--mut)' }}>
          {prompt.hint}
        </div>
      )}
    </>
  )
}

/** The team lookup decides which path Connect takes: until it settles the
 *  action is disabled, so a click can never start the personal path early. */
function ConnectPending({ entry }: { entry: CatalogEntry }): React.JSX.Element {
  return (
    <>
      <Button kind="primary" size="sm" disabled>
        Connect {entry.name}
      </Button>
      <div style={{ marginTop: 8 }}>
        <Spinner size={12} />
      </div>
    </>
  )
}

/** The plain Connect button (legacy wizard), with the linked-account line and,
 *  after a failed team lookup, a non-fatal notice. */
function ConnectAction({
  entry,
  linkedAccount,
  notice,
  onBegin
}: Pick<ConnectWizardModalProps, 'entry' | 'linkedAccount' | 'onBegin'> & {
  notice: string | null
}): React.JSX.Element {
  return (
    <>
      <Button kind="primary" size="sm" onClick={onBegin}>
        Connect {entry.name}
      </Button>
      {notice && (
        <div role="status" style={{ marginTop: 8, fontSize: 11, color: 'var(--mut)' }}>
          {notice}
        </div>
      )}
      {linkedAccount && (
        <div
          data-testid="cw-linked-account"
          style={{ marginTop: 8, fontSize: 11, color: 'var(--mut)' }}
        >
          Using your linked account{linkedAccount.login ? ` · ${linkedAccount.login}` : ''}
        </div>
      )}
    </>
  )
}

/** The step-zero call to action: pick the export file(s), or start the OAuth flow. */
function IdleAction({
  entry,
  linkedAccount,
  picker,
  onBegin,
  onPickFiles,
  onClose
}: Pick<
  ConnectWizardModalProps,
  'entry' | 'linkedAccount' | 'onBegin' | 'onPickFiles' | 'onClose'
> & { picker: TeamPicker }): React.JSX.Element {
  if (entry.mode === 'local-bridge') return <BridgeAction entry={entry} onClose={onClose} />
  if (entry.mode === 'oauth' && picker.loading) return <ConnectPending entry={entry} />
  if (entry.mode === 'oauth' && picker.sections) {
    // A team repo is staged for begin(); the account entries are the unchanged
    // linked-account / sign-in paths, which begin() already resolves.
    return (
      <SelectionPicker
        items={[]}
        sections={picker.sections}
        paging={picker.paging ?? undefined}
        onSelect={(items) => {
          const item = items?.[0]
          if (!item) return
          const isAccountEntry = item.id === ACCOUNT_ENTRY_ID || item.id === SIGN_IN_ENTRY_ID
          if (!isAccountEntry) stageTeamPick(item)
          onBegin()
        }}
      />
    )
  }
  if (entry.mode !== 'export-file') {
    return (
      <ConnectAction
        entry={entry}
        linkedAccount={linkedAccount}
        notice={picker.failedNotice}
        onBegin={onBegin}
      />
    )
  }
  return <ExportFilePick entry={entry} onPickFiles={onPickFiles} />
}

/** Whatever input the busy flow is waiting on, or its live progress line. */
function BusyAction({
  state,
  onSelect,
  onSubmitConfig,
  onChooseAccess,
  onRefreshSelection
}: Pick<
  ConnectWizardModalProps,
  'state' | 'onSelect' | 'onSubmitConfig' | 'onChooseAccess' | 'onRefreshSelection'
>): React.JSX.Element {
  if (state?.phase !== 'busy') return <Spinner />
  if (state.accessModes) {
    return <AccessPicker accessModes={state.accessModes} onChooseAccess={onChooseAccess} />
  }
  if (state.selectable && state.selectable.length > 0) {
    return (
      <SelectionPicker
        key={state.sourceId}
        items={state.selectable}
        mode={state.selectionMode}
        label={state.selectionLabel}
        onSelect={onSelect}
        onRefresh={onRefreshSelection}
      />
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
  props: ConnectWizardModalProps & {
    status: 'idle' | 'busy' | 'done' | 'error'
    picker: TeamPicker
  }
): React.JSX.Element {
  if (props.status === 'done') {
    return (
      <Button kind="primary" size="sm" onClick={props.onClose}>
        Done
      </Button>
    )
  }
  if (props.status === 'error') {
    // A committed-export connector retries by picking the file again — its
    // begin() is the OAuth path and would honestly (but uselessly) fail.
    // Likewise a team-picker connector: picking again IS the retry.
    if (props.entry.mode === 'export-file' || props.picker.sections)
      return <IdleAction {...props} />
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

/** The derived rail, plus the team sections whose presence changes it. The team
 *  path skips the grant and sign-in like a linked account does — until the user
 *  actually chooses to sign in with their own account. */
function useWizardRail(
  entry: CatalogEntry,
  scope: WizardScope,
  linkedAccount: { login: string | null } | null,
  state: ConnectionState | undefined
): { steps: readonly WizardStep[]; picker: TeamPicker } {
  const picker = useTeamPicker(entry, scope, linkedAccount?.login ?? null)
  const signingIn =
    state?.phase === 'busy' && (state.stage === 'access' || state.stage === 'authorize')
  const skipsSignIn = linkedAccount !== null || (picker.sections !== null && !signingIn)
  return { steps: wizardSteps({ ...entry, scope, linkedAccount: skipsSignIn }), picker }
}

export function ConnectWizardModal(props: ConnectWizardModalProps): React.JSX.Element {
  const { entry, state, onClose, scope = 'project', linkedAccount = null } = props
  const solMode = useSettingsStore((s) => s.solMode)
  const { steps, picker } = useWizardRail(entry, scope, linkedAccount, state)
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
              <ActionArea {...props} status={status} picker={picker} />
            </div>
          </div>
        </div>
      </div>
    </ModalShell>
  )
}
