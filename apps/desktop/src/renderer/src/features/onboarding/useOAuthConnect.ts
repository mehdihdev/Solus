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
import { runOAuthConnect, type ConfigureStep, type OAuthConnectApi } from './oauthConnect'
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
  /** Begin the real connect for a project + provider. */
  start: (projectId: string, provider: string, options?: OAuthConnectStartOptions) => Promise<void>
  /** Resolve the in-tile picker. */
  select: (items: SelectableItem[] | null) => void
  /** Resolve the in-tile connector-details form. */
  submitConfig: (values: Record<string, string>) => void
  /** Resolve the in-tile connect-time grant choice. */
  chooseAccess: (mode: string | null) => void
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

/** Park until the tile's own handler resolves the choice. */
function awaitChoice<T>(ref: { current: Resolver<T> }): Promise<T | null> {
  return new Promise<T | null>((resolve) => {
    ref.current = (value) => {
      ref.current = null
      resolve(value)
    }
  })
}

export function useOAuthConnect(): UseOAuthConnect {
  const setConnection = useOnboardingStore((s) => s.setConnection)
  // Resolvers for the in-tile steps; the orchestration awaits the user's input.
  const selectChoice = useRef<Resolver<SelectableItem[]>>(null)
  const configSubmit = useRef<Resolver<Record<string, string>>>(null)
  const accessChoice = useRef<Resolver<string>>(null)

  const start = async (
    projectId: string,
    provider: string,
    options: OAuthConnectStartOptions = {}
  ): Promise<void> => {
    const bridge = getDesktopOAuthBridge()
    // The CONNECTOR redirect URL — constant, no per-flow query. Sign-in keeps
    // its own nonce-carrying URL; only strict connector providers need this.
    const redirectUri = bridge ? await bridge.getConnectorRedirectUrl() : ''
    const onProgress = (state: ConnectionState): void => setConnection(provider, state)

    const configure: ConfigureStep = options.selection
      ? selectionConfigureStep({
          selection: options.selection,
          listSelectable,
          onProgress,
          onSelect: () => awaitChoice(selectChoice)
        })
      : fieldsConfigureStep({
          fields: options.configFields ?? [],
          onProgress,
          onSubmitConfig: () => awaitChoice(configSubmit)
        })

    const chooseAccess = accessChoiceStep({
      accessModes: options.accessModes,
      onProgress,
      onChoose: () => awaitChoice(accessChoice)
    })

    await runOAuthConnect(
      { api: oauthApi, bridge, onProgress, configure, chooseAccess },
      projectId,
      provider,
      { redirectUri, displayName: options.displayName }
    )
  }

  return {
    start,
    select: (items) => selectChoice.current?.(items),
    submitConfig: (values) => configSubmit.current?.(values),
    chooseAccess: (mode) => accessChoice.current?.(mode)
  }
}
