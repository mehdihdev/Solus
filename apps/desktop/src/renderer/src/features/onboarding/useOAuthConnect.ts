// Component-side glue for the real OAuth connectors (SOLUSDEV-103, generalised
// from the GitHub-only hook): binds the typed API singleton + onboarding store
// to the pure orchestration in oauthConnect.ts, and bridges the in-tile
// resolvers (a user click) to the async steps the orchestration awaits.
//
// `start` takes the PROVIDER, and which post-auth step runs is decided by what
// the connector DECLARES — a `selection` (pick repos/documents) or plain
// `config_fields` (type them in) — never by a provider id. So a new OAuth
// connector needs no change here.
import { useRef } from 'react'
import {
  startOAuth,
  exchangeOAuth,
  listSelectable,
  updateSource,
  triggerSync,
  getSyncs,
  getSource,
  type IntegrationAccessModes,
  type IntegrationSelection,
  type SelectableItem
} from '../../lib/api/resources'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { accessChoiceStep } from './accessChoiceStep'
import { fieldsConfigureStep } from './fieldsConfigureStep'
import { selectionConfigureStep } from './selectionConfigureStep'
import {
  runOAuthConnect,
  type ConfigureStep,
  type OAuthConnectApi,
  type OAuthConnectResult
} from './oauthConnect'
import { useOnboardingStore, type ConnectionState } from './onboardingStore'

/** The typed API surface the orchestration runs against (app singleton). */
const oauthApi: OAuthConnectApi = {
  startOAuth,
  exchangeOAuth,
  updateSource,
  triggerSync,
  getSyncs,
  getSource
}

export interface OAuthConnectStartOptions {
  /** Human name for progress copy; falls back to the provider id. */
  displayName?: string
  /** The connector's config keys from the live registry. */
  configFields?: readonly string[]
  /** How this connector lets a user choose what to track, if at all. */
  selection?: IntegrationSelection | null
  /** How much power the user grants at connect time, if there is a choice. */
  accessModes?: IntegrationAccessModes | null
}

export interface UseOAuthConnect {
  /** Begin the real connect for a project + provider. Resolves with the
   * structured result so callers can clean up after a cancelled attempt. */
  start: (
    projectId: string,
    provider: string,
    options?: OAuthConnectStartOptions
  ) => Promise<OAuthConnectResult>
  /** Resolve the in-flow picker. */
  select: (items: SelectableItem[] | null) => void
  /** Resolve the in-flow connector-details form. */
  submitConfig: (values: Record<string, string>) => void
  /** Resolve the in-flow connect-time grant choice. */
  chooseAccess: (mode: string | null) => void
  /** Abandon the in-flight connect: any pending user-input step resolves null
   * (its own cancel path), and any LATER input request resolves null
   * immediately instead of parking forever — so the flow always settles and
   * `start`'s result can drive cleanup. Cleared by the next `start`. */
  cancel: () => void
}

/** The start options a catalog tile implies — shared by both dispatch sites so
 * neither has to know what the flow needs from an entry. */
export function connectOptions(integ: {
  name: string
  configFields: readonly string[]
  selection?: IntegrationSelection | null
  accessModes?: IntegrationAccessModes | null
}): OAuthConnectStartOptions {
  return {
    displayName: integ.name,
    configFields: integ.configFields,
    selection: integ.selection,
    accessModes: integ.accessModes
  }
}

type Resolver<T> = ((value: T | null) => void) | null

/** One `start()` invocation. Cancellation is PER ATTEMPT so a late-settling
 * abandoned flow can neither consume a newer attempt's input nor be governed
 * by a newer attempt's latch. */
interface Attempt {
  cancelled: boolean
}

/** Park until the flow's own handler resolves the choice. A cancelled or
 * superseded attempt gets null immediately — it must settle, never park. */
function awaitChoice<T>(
  ref: { current: Resolver<T> },
  attempt: Attempt,
  current: { current: Attempt | null }
): Promise<T | null> {
  if (attempt.cancelled || current.current !== attempt) return Promise.resolve(null)
  return new Promise<T | null>((resolve) => {
    ref.current = (value) => {
      ref.current = null
      resolve(value)
    }
  })
}

export function useOAuthConnect(): UseOAuthConnect {
  const setConnection = useOnboardingStore((s) => s.setConnection)
  // Resolvers for the in-flow steps; the orchestration awaits the user's input.
  const selectChoice = useRef<Resolver<SelectableItem[]>>(null)
  const configSubmit = useRef<Resolver<Record<string, string>>>(null)
  const accessChoice = useRef<Resolver<string>>(null)
  const currentAttempt = useRef<Attempt | null>(null)

  const start = async (
    projectId: string,
    provider: string,
    options: OAuthConnectStartOptions = {}
  ): Promise<OAuthConnectResult> => {
    const attempt: Attempt = { cancelled: false }
    currentAttempt.current = attempt
    const bridge = getDesktopOAuthBridge()
    // The CONNECTOR redirect URL — constant, no per-flow query. Sign-in keeps
    // its own nonce-carrying URL; only strict connector providers need this.
    const redirectUri = bridge ? await bridge.getConnectorRedirectUrl() : ''
    // A cancelled attempt goes quiet: its progress must not resurrect tile
    // state the wizard already forgot.
    const onProgress = (state: ConnectionState): void => {
      if (!attempt.cancelled) setConnection(provider, state)
    }

    const configure: ConfigureStep = options.selection
      ? selectionConfigureStep({
          selection: options.selection,
          listSelectable,
          onProgress,
          onSelect: () => awaitChoice(selectChoice, attempt, currentAttempt)
        })
      : fieldsConfigureStep({
          fields: options.configFields ?? [],
          onProgress,
          onSubmitConfig: () => awaitChoice(configSubmit, attempt, currentAttempt)
        })

    const chooseAccess = accessChoiceStep({
      accessModes: options.accessModes,
      onProgress,
      onChoose: () => awaitChoice(accessChoice, attempt, currentAttempt)
    })

    return runOAuthConnect(
      { api: oauthApi, bridge, onProgress, configure, chooseAccess },
      projectId,
      provider,
      { redirectUri, displayName: options.displayName }
    )
  }

  const cancel = (): void => {
    if (currentAttempt.current) currentAttempt.current.cancelled = true
    selectChoice.current?.(null)
    configSubmit.current?.(null)
    accessChoice.current?.(null)
    // Settle a flow parked on the browser handshake NOW — otherwise the
    // loopback stays armed and a later browser completion would mint and
    // store a token for an attempt the user abandoned. A rejected invoke is
    // swallowed: nothing depends on the result, and the flow's own timeout
    // remains the backstop.
    void getDesktopOAuthBridge()
      ?.cancelOAuth?.()
      ?.catch(() => undefined)
  }

  return {
    start,
    select: (items) => selectChoice.current?.(items),
    submitConfig: (values) => configSubmit.current?.(values),
    chooseAccess: (mode) => accessChoice.current?.(mode),
    cancel
  }
}
