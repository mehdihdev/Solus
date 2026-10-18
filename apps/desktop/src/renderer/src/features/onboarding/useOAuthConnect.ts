// Component-side glue for the real OAuth connectors (SOLUSDEV-103, generalised
// from the GitHub-only hook): binds the typed API singleton + onboarding store
// to the pure orchestration in oauthConnect.ts, and bridges the in-tile
// resolvers (a user click) to the async steps the orchestration awaits.
//
// `start` takes the PROVIDER, and which post-auth step runs is decided by what
// the connector DECLARES — a `selection` (pick repos/documents) or plain
// `config_fields` (type them in) — never by a provider id. So a new OAuth
// connector needs no change here.
import { useCallback, useEffect, useRef } from 'react'
import { useAuthStore } from '../../store/authStore'
import {
  startOAuth,
  exchangeOAuth,
  createSource,
  listSelectable,
  updateSource,
  triggerSync,
  getSyncs,
  getJob,
  getSource,
  startHostedOAuth,
  exchangeHostedOAuth,
  type IntegrationAccessModes,
  type IntegrationHosted,
  type IntegrationSelection,
  type SelectableItem
} from '../../lib/api/resources'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { githubOrgErrorCode } from '../../lib/api/resources.teamGithub'
import { useSettingsStore } from '../../store/settingsStore'
import { teamBindErrorMessage } from './teamRepoSection'
import { accessChoiceStep } from './accessChoiceStep'
import { runAccountConnect, type AccountConnectResult } from './accountConnect'
import { addOnStep } from './addOnStep'
import { accountAddOnStep } from './accountAddOnStep'
import {
  getAccountHosted,
  startAccountHosted,
  exchangeAccountHosted
} from '../../lib/api/resources.hosted'
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
  createSource,
  updateSource,
  triggerSync,
  getSyncs,
  getJob,
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
  /** A vendor-hosted add-on this connector carries, enabled as part of the
   *  connect rather than on a button afterwards (SOLUSDEV-168). */
  hosted?: IntegrationHosted | null
  /** SOLUSDEV-241: an account the user already linked on Home. Present, the
   *  project is bound to it and no browser handshake runs. */
  linkedConnection?: { id: string; login: string | null } | null
  /** SOLUSDEV-216: a repository picked from the team's GitHub installation. Present,
   *  the project binds through the installation with that repo — no sign-in, no
   *  account — and the configure step is already answered. */
  teamRepo?: SelectableItem | null
}

export interface UseOAuthConnect {
  /** Begin the real connect for a project + provider. Resolves with the
   * structured result so callers can clean up after a cancelled attempt. */
  start: (
    projectId: string,
    provider: string,
    options?: OAuthConnectStartOptions
  ) => Promise<OAuthConnectResult>
  /** SOLUSDEV-241: bind a provider ACCOUNT with no project (Home). Only the
   *  grant choice and the handshake run; what to track is chosen per project. */
  startAccount: (
    provider: string,
    options?: OAuthConnectStartOptions
  ) => Promise<AccountConnectResult>
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
  hosted?: IntegrationHosted | null
}): OAuthConnectStartOptions {
  return {
    displayName: integ.name,
    configFields: integ.configFields,
    selection: integ.selection,
    accessModes: integ.accessModes,
    hosted: integ.hosted ?? null
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

function useOAuthInputs() {
  const setConnection = useOnboardingStore((s) => s.setConnection)
  // Resolvers for the in-flow steps; the orchestration awaits the user's input.
  const selectChoice = useRef<Resolver<SelectableItem[]>>(null)
  const configSubmit = useRef<Resolver<Record<string, string>>>(null)
  const accessChoice = useRef<Resolver<string>>(null)
  const currentAttempt = useRef<Attempt | null>(null)

  const cancel = useCallback((): void => {
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
  }, [])

  useEffect(() => {
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.accessToken !== previous.accessToken) cancel()
    })
    return () => {
      unsubscribe()
      cancel()
    }
  }, [cancel])

  return { setConnection, selectChoice, configSubmit, accessChoice, currentAttempt, cancel }
}

export function useOAuthConnect(): UseOAuthConnect {
  const inputs = useOAuthInputs()
  return {
    start: projectConnect(inputs),
    startAccount: accountConnect(inputs),
    select: (items) => inputs.selectChoice.current?.(items),
    submitConfig: (values) => inputs.configSubmit.current?.(values),
    chooseAccess: (mode) => inputs.accessChoice.current?.(mode),
    cancel: inputs.cancel
  }
}

function projectConnect(inputs: ReturnType<typeof useOAuthInputs>): UseOAuthConnect['start'] {
  const { setConnection, selectChoice, configSubmit, accessChoice, currentAttempt } = inputs
  return async (
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
      if (!attempt.cancelled && currentAttempt.current === attempt) setConnection(provider, state)
    }

    const route = bindRoute(options, onProgress)

    const configure: ConfigureStep =
      route.configure ??
      configureFromShape(options, onProgress, {
        select: () => awaitChoice(selectChoice, attempt, currentAttempt),
        submitConfig: () => awaitChoice(configSubmit, attempt, currentAttempt)
      })

    const chooseAccess = accessChoiceStep({
      accessModes: options.accessModes,
      onProgress,
      onChoose: () => awaitChoice(accessChoice, attempt, currentAttempt)
    })

    const addOn = addOnStep({
      hosted: options.hosted ?? null,
      bridge,
      api: { startHostedOAuth, exchangeHostedOAuth },
      onProgress,
      isCancelled: () => attempt.cancelled
    })

    return runOAuthConnect(
      {
        api: route.api,
        bridge,
        onProgress: route.onProgress,
        configure,
        chooseAccess,
        addOn
      },
      projectId,
      provider,
      {
        redirectUri,
        displayName: options.displayName,
        ...route.link
      }
    )
  }
}

/** Which configure step a connector's declared shape implies. */
function configureFromShape(
  options: OAuthConnectStartOptions,
  onProgress: (state: ConnectionState) => void,
  waits: {
    select: () => Promise<SelectableItem[] | null>
    submitConfig: () => Promise<Record<string, string> | null>
  }
): ConfigureStep {
  return options.selection
    ? selectionConfigureStep({
        selection: options.selection,
        listSelectable,
        onProgress,
        onSelect: waits.select
      })
    : fieldsConfigureStep({
        fields: options.configFields ?? [],
        onProgress,
        onSubmitConfig: waits.submitConfig
      })
}

/** Marks "bind without a handshake" for the orchestration; the team api below
 *  swaps the account credential for the installation. */
const TEAM_BIND = { id: 'team-installation', login: null } as const

/** Rewrites the orchestration's account-bind copy for the team installation. */
const TEAM_LINK_LABEL = "Linking your team's GitHub organization…"

/**
 * SOLUSDEV-216: the team-installation bind, expressed as three injected pieces
 * so the unchanged orchestration (link → configure → index) runs it: an api
 * whose source creation sends `installation: true` and the picked repo, a
 * configure step that is already answered, and progress copy that names the
 * organization. Org failures surface as named, SOL-mode-aware errors.
 */
function teamRepoBind(
  repo: SelectableItem,
  onProgress: (state: ConnectionState) => void
): Pick<BindRoute, 'api' | 'onProgress' | 'configure'> {
  const config = repo.config ?? { repo: repo.id }
  return {
    api: {
      ...oauthApi,
      createSource: async (projectId, input) => {
        try {
          return await createSource(projectId, {
            type: input.type,
            name: input.name,
            installation: true,
            config
          })
        } catch (error) {
          const code = githubOrgErrorCode(error)
          const named = code && teamBindErrorMessage(code, useSettingsStore.getState().solMode)
          throw named ? new Error(named) : error
        }
      }
    },
    configure: async () => ({ config, label: repo.name }),
    onProgress: (state) =>
      onProgress(
        state.phase === 'busy' && state.stage === 'link'
          ? { ...state, label: TEAM_LINK_LABEL }
          : state
      )
  }
}

interface BindRoute {
  api: OAuthConnectApi
  onProgress: (state: ConnectionState) => void
  /** Present only when the configure step is already answered (team repo). */
  configure: ConfigureStep | null
  /** The orchestration's `linkedConnection` option. */
  link: { linkedConnection?: { id: string; login: string | null } }
}

/** How this start binds the project: through the team installation, a linked
 *  account, or (neither) the browser sign-in. */
function bindRoute(
  options: OAuthConnectStartOptions,
  onProgress: (state: ConnectionState) => void
): BindRoute {
  if (options.teamRepo) {
    return { ...teamRepoBind(options.teamRepo, onProgress), link: { linkedConnection: TEAM_BIND } }
  }
  const linked = options.linkedConnection
  return {
    api: oauthApi,
    onProgress,
    configure: null,
    link: linked ? { linkedConnection: linked } : {}
  }
}

function accountConnect(
  inputs: ReturnType<typeof useOAuthInputs>
): UseOAuthConnect['startAccount'] {
  const { setConnection, accessChoice, currentAttempt } = inputs
  return async (
    provider: string,
    options: OAuthConnectStartOptions = {}
  ): Promise<AccountConnectResult> => {
    const attempt: Attempt = { cancelled: false }
    currentAttempt.current = attempt
    const bridge = getDesktopOAuthBridge()
    const redirectUri = bridge ? await bridge.getConnectorRedirectUrl() : ''
    const onProgress = (state: ConnectionState): void => {
      if (!attempt.cancelled && currentAttempt.current === attempt) setConnection(provider, state)
    }
    const chooseAccess = accessChoiceStep({
      accessModes: options.accessModes,
      onProgress,
      onChoose: () => awaitChoice(accessChoice, attempt, currentAttempt)
    })
    return runAccountConnect(
      {
        api: { startOAuth, exchangeOAuth },
        bridge,
        onProgress,
        chooseAccess,
        addOn: accountAddOnStep({
          hosted: options.hosted ?? null,
          bridge,
          onProgress,
          api: { getAccountHosted, startAccountHosted, exchangeAccountHosted },
          isCancelled: () => attempt.cancelled || currentAttempt.current !== attempt
        })
      },
      provider,
      { redirectUri, displayName: options.displayName }
    )
  }
}
