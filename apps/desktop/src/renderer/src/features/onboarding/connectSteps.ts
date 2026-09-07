// The connect wizard's pure step model (SOLUSDEV-165). Derives the step rail
// from what the connector DECLARES in the live registry — mode, access modes,
// selection, config fields — never from a provider id, so a connector the app
// has never seen still gets a correct rail. Instruction copy is SOL-mode aware
// (ADR-016): Guide teaches, Expert leads with the action.
import type { IntegrationAccessModes, IntegrationSelection } from '../../lib/api/resources'
import type { SolMode } from '../../store/settingsStore'
import type { ConnectMode } from './integrationCatalog'
import type { ConnectionState, ConnectStage } from './onboardingStore'
import { plural } from './selectionConfigureStep'

export type WizardStepId = 'access' | 'authorize' | 'configure' | 'file' | 'index' | 'bridge'

export interface WizardStep {
  readonly id: WizardStepId
  readonly title: string
}

/** The slice of a catalog entry the rail is derived from. */
export interface WizardShape {
  readonly mode: ConnectMode
  readonly accessModes: IntegrationAccessModes | null
  readonly selection: IntegrationSelection | null
  readonly configFields: readonly string[]
  /** SOLUSDEV-241: `account` binds a provider account with no project (Home)
   *  — the rail ends at the sign-in. Default `project`. */
  readonly scope?: WizardScope
  /** SOLUSDEV-241: the user already holds a linked account for this provider,
   *  so the wizard skips the grant + sign-in and goes straight to picking. */
  readonly linkedAccount?: boolean
}

export type WizardScope = 'project' | 'account'

/** Where the wizard is on its rail. `stepIndex` is past the end when done. */
export interface WizardPosition {
  readonly status: 'idle' | 'busy' | 'done' | 'error'
  readonly stepIndex: number
}

/** The steps this connector's declared shape implies, in order. */
export function wizardSteps(shape: WizardShape): readonly WizardStep[] {
  // A local tool has no credential flow: it connects when its vendor app runs
  // its server and the companion bridges it — one step, stated plainly.
  if (shape.mode === 'local-bridge') return [{ id: 'bridge', title: 'Connect on this computer' }]
  if (shape.mode === 'export-file') {
    return [
      { id: 'file', title: 'Choose export' },
      { id: 'index', title: 'Build graph' }
    ]
  }
  const steps: WizardStep[] = []
  // A linked account already carries a grant — asking again would be asking
  // for something the user already gave (SOLUSDEV-241).
  if (!shape.linkedAccount) {
    // A single offered grant is sent implicitly (accessChoiceStep) — no step.
    if (shape.accessModes && shape.accessModes.modes.length > 1) {
      steps.push({ id: 'access', title: 'Choose access' })
    }
    steps.push({ id: 'authorize', title: 'Sign in' })
  }
  // Account scope binds the account and stops: what to track is a per-project
  // choice, made from the Workspace later.
  if (shape.scope === 'account') return steps
  if (shape.selection) {
    steps.push({ id: 'configure', title: `Pick ${plural(shape.selection.label)}` })
  } else if (shape.configFields.length > 0) {
    steps.push({ id: 'configure', title: 'Enter details' })
  }
  steps.push({ id: 'index', title: 'Build graph' })
  return steps
}

/** The token exchange completes the sign-in; it has no step of its own. */
const STAGE_STEP: Readonly<Record<ConnectStage, WizardStepId>> = {
  access: 'access',
  authorize: 'authorize',
  link: 'authorize',
  configure: 'configure',
  index: 'index'
}

/** Map a live connection state onto the rail. */
export function wizardPosition(
  steps: readonly WizardStep[],
  state: ConnectionState | undefined
): WizardPosition {
  if (!state) return { status: 'idle', stepIndex: 0 }
  if (state.phase === 'done') return { status: 'done', stepIndex: steps.length }
  if (state.phase === 'error') return { status: 'error', stepIndex: 0 }
  const wanted = state.stage ? STAGE_STEP[state.stage] : undefined
  const found = steps.findIndex((step) => step.id === wanted)
  return { status: 'busy', stepIndex: found >= 0 ? found : 0 }
}

export interface InstructionContext {
  /** Human name of the integration ("GitHub"). */
  readonly name: string
  /** The connector's own selection noun ("repository"), when it has one. */
  readonly selectionLabel?: string
}

type Copy = (ctx: InstructionContext) => string

const GUIDE: Readonly<Record<WizardStepId, Copy>> = {
  access: ({ name }) =>
    `Choose how much access Solus gets to your ${name} account. Starting read-only is fine — ` +
    'any edit Solus ever proposes still asks you first, whatever you grant here.',
  authorize: ({ name }) =>
    `Your browser opens ${name}'s own sign-in page. Solus never sees your password — ` +
    'it receives a scoped token it can only use for what you approve.',
  configure: ({ name, selectionLabel }) =>
    selectionLabel
      ? `Pick which ${plural(selectionLabel)} Solus should track. Only what you pick is read, ` +
        'and each becomes a domain of entities in your graph.'
      : `Enter the connector details — ${name} needs these ids so Solus knows exactly what to read.`,
  file: ({ name }) =>
    `Choose the netlist export committed in your ${name} project. Solus parses it into ` +
    'components and nets — the electronics domain of your graph.',
  index: () =>
    'Solus is reading the source and building graph entities from it. ' +
    'The first sync can take a moment.',
  bridge: ({ name }) =>
    `${name} runs its own local server on this computer; the Solus companion bridges it. ` +
    'There is no account to link — follow the steps below in the vendor app.'
}

const EXPERT: Readonly<Record<WizardStepId, Copy>> = {
  access: () => 'Choose the grant.',
  authorize: () => 'Sign in via your browser.',
  configure: ({ selectionLabel }) =>
    selectionLabel
      ? `Pick the ${plural(selectionLabel)} to track.`
      : 'Enter the connector details.',
  file: () => 'Choose the committed netlist export.',
  index: () => 'Indexing…',
  bridge: ({ name }) => `${name} runs locally; the companion bridges it.`
}

/** What the current step tells the user, in their SOL mode. */
export function stepInstruction(
  step: Pick<WizardStep, 'id'>,
  ctx: InstructionContext,
  mode: SolMode
): string {
  return (mode === 'Guide' ? GUIDE : EXPERT)[step.id](ctx)
}

/** The mode-aware lead-in above a backend-authored connect disclosure
 *  (ADR-016). The NOTICE ITSELF is never rewritten by mode: it is a consent
 *  statement the backend authored, so it renders verbatim in both modes and is
 *  never collapsed or hidden — only its framing changes. Expert mode gets to be
 *  terse; it does not get to hide what a connection turns on. */
const NOTICE_LEAD: Readonly<Record<SolMode, string>> = {
  Guide: 'This connection also turns something on:',
  Expert: 'Also enabled:'
}

export function noticeLead(mode: SolMode): string {
  return NOTICE_LEAD[mode]
}
