// A vendor-hosted MCP add-on on a connected source (SOLUSDEV-168).
//
// FeatureScript is NOT a separate tile — it rides the Onshape connection the
// customer already made, so it lives here, on the source, rather than in the
// connect wizard. Three verified reasons it cannot live in the wizard:
//
//  * the wizard CANCELS its attempt on close (`useConnectWizard.close`), and
//    subscribing is an external browser purchase that can wait on a company
//    administrator — no in-wizard state would survive it;
//  * Home resets nothing, but the wizard is modal: wizard-resident
//    state is lost the moment the user navigates;
//  * a teammate who joins a project where Onshape is already connected never
//    opens the wizard at all (the backend REUSES the project's existing source),
//    so a wizard-only affordance would be unreachable for them.
//
// Everything authoritative therefore comes from the SOURCE, which the Sources
// screen already polls. Local state here is transient work only.
//
// Generic by construction: every label and every URL comes from the backend's
// own hosted registry via `Integration.hosted`, so the next hosted server is one
// backend entry and no change to this file.
import { useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import {
  exchangeHostedOAuth,
  probeHostedStatus,
  startHostedOAuth,
  type IntegrationHosted,
  type Source
} from '../../lib/api/resources'
import { getDesktopHostedBridge, getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { noticeLead } from '../onboarding/connectSteps'
import { noBridgeError } from '../onboarding/oauthConnect'
import { useSettingsStore } from '../../store/settingsStore'
import { hostedDetail, hostedState } from './sourcePresentation'

export interface HostedAddOnRowProps {
  readonly source: Source
  readonly projectId: string
  readonly hosted: IntegrationHosted
  /** The connector's display name ("Onshape"), for the store-link copy. */
  readonly providerName: string
  /** Re-read the source list so the new state lands. */
  readonly onChanged: () => void
}

export function HostedAddOnRow(props: HostedAddOnRowProps): React.JSX.Element {
  if (props.source.connection_id)
    return (
      <p style={{ fontSize: 11, color: 'var(--mut)' }}>
        {props.hosted.display_name} is managed by the linked account owner in Home.
      </p>
    )
  return <LegacyHostedAddOnRow {...props} />
}

function LegacyHostedAddOnRow({
  source,
  projectId,
  hosted,
  providerName,
  onChanged
}: HostedAddOnRowProps): React.JSX.Element {
  const [busy, setBusy] = useState<'enabling' | 'checking' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const solMode = useSettingsStore((s) => s.solMode)
  const state = hostedState(source, hosted.server)
  const detail = hostedDetail(source, hosted.server)

  const { enable, recheck } = hostedActions({
    source,
    projectId,
    hosted,
    onChanged,
    setBusy,
    setError
  })

  const openStore = (): void => openSubscriptionStore(hosted, setError)

  return (
    <div style={{ paddingLeft: 24, paddingBottom: 8 }} data-hosted-state={state}>
      {state === 'ready' && (
        <Mono style={{ fontSize: 10.5, color: 'var(--ok)' }}>
          {hosted.display_name.toUpperCase()} ON
        </Mono>
      )}

      {state === 'subscription_required' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* The vendor's OWN words. A refusal we did not author is more
              actionable than our paraphrase, and we genuinely cannot tell a
              missing subscription from an admin-gated Labs account. */}
          <Mono style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            {detail ??
              `${hosted.display_name} is not available on this ${providerName} account yet.`}{' '}
            It needs a {providerName} subscription to the app, and on a company account an
            administrator may have to permit it first.
          </Mono>
          <div style={{ display: 'flex', gap: 8 }}>
            {hosted.subscribe_url ? (
              <button type="button" onClick={openStore}>
                Open {providerName} App Store
              </button>
            ) : null}
            <button type="button" onClick={() => void recheck()} disabled={busy !== null}>
              {busy === 'checking' ? 'Checking…' : 'I’ve subscribed — check again'}
            </button>
          </div>
        </div>
      )}

      {state === 'not_connected' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {hosted.notice ? (
            <Mono style={{ fontSize: 10.5, color: 'var(--mut)', whiteSpace: 'pre-wrap' }}>
              {noticeLead(solMode)} {hosted.notice}
            </Mono>
          ) : null}
          <div>
            <button type="button" onClick={() => void enable()} disabled={busy !== null}>
              {busy === 'enabling' ? 'Waiting for your browser…' : `Enable ${hosted.display_name}`}
            </button>
          </div>
        </div>
      )}

      {error !== null && (
        <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 4 }}>{error}</div>
      )}
    </div>
  )
}

interface HostedActionContext {
  source: Source
  projectId: string
  hosted: IntegrationHosted
  onChanged: () => void
  setBusy: (value: 'enabling' | 'checking' | null) => void
  setError: (message: string | null) => void
}

function hostedActions({
  source,
  projectId,
  hosted,
  onChanged,
  setBusy,
  setError
}: HostedActionContext): { enable: () => Promise<void>; recheck: () => Promise<void> } {
  // The SECOND browser trip. It reuses the connector loopback wholesale: the
  // backend registers byte-for-byte the same redirect the connector flow uses,
  // and the nonce is the backend's own OAuth state — same channel, same port,
  // same CSRF check, no new capture to sequence.
  const enable = async (): Promise<void> => {
    const bridge = getDesktopOAuthBridge()
    if (!bridge) {
      setError(noBridgeError(hosted.display_name))
      return
    }
    setBusy('enabling')
    setError(null)
    try {
      const start = await startHostedOAuth(projectId, source.id, hosted.server)
      const callback = await bridge.awaitOAuth(start.authorize_url, start.state)
      // The loopback capture is SINGLE-FLIGHT: a connect already running in the
      // wizard makes this resolve "A sign-in is already in progress." before any
      // browser opens. Shown verbatim — it is already honest and actionable.
      if (callback.error) {
        setError(callback.error)
        return
      }
      if (!callback.code) {
        setError(`${hosted.display_name} sign-in was cancelled.`)
        return
      }
      await exchangeHostedOAuth(projectId, source.id, hosted.server, {
        state: start.state,
        code: callback.code
      })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : `Couldn't enable ${hosted.display_name}.`)
    } finally {
      setBusy(null)
    }
  }

  // Subscribing cannot be detected any other way: there is no purchase API and
  // no webhook, and the vendor documents that a redirect back with success=true
  // does NOT mean a purchase happened. So the user tells us to look again.
  const recheck = async (): Promise<void> => {
    setBusy('checking')
    setError(null)
    try {
      await probeHostedStatus(projectId, source.id, hosted.server)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't check your subscription.")
    } finally {
      setBusy(null)
    }
  }

  return { enable, recheck }
}

function openSubscriptionStore(
  hosted: IntegrationHosted,
  setError: (message: string | null) => void
): void {
  const url = hosted.subscribe_url
  if (!url) return
  setError(null)
  void getDesktopHostedBridge()
    ?.openStore(url)
    .then((r) => {
      if (!r.ok) setError("Couldn't open the App Store page.")
    })
    .catch(() => setError("Couldn't open the App Store page."))
}
