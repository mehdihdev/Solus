import type { IntegrationHosted } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import { noticeLead } from '../onboarding/connectSteps'
import { useAccountHosted } from './useAccountHosted'
export interface AccountHostedProps {
  connectionId: string
  hosted: IntegrationHosted
}
export function AccountHostedRow({ connectionId, hosted }: AccountHostedProps): React.JSX.Element {
  const state = useAccountHosted(connectionId, hosted)
  const ready = state.status?.state === 'ready'
  return (
    <div style={{ fontSize: 12, paddingTop: 8 }}>
      {ready ? (
        <span>{hosted.display_name} ready</span>
      ) : (
        <Recovery state={state} hosted={hosted} />
      )}
      {state.monitoring && !ready && (
        <p role="status">
          Checking for completion…{' '}
          <button type="button" onClick={state.stop}>
            Stop checking
          </button>
        </p>
      )}
      {state.busy && <p role="status">Connecting…</p>}
      {state.error && <p role="alert">{state.error}</p>}
    </div>
  )
}

function Recovery({
  state,
  hosted
}: {
  state: ReturnType<typeof useAccountHosted>
  hosted: IntegrationHosted
}): React.JSX.Element {
  const mode = useSettingsStore((settings) => settings.solMode)
  return (
    <>
      <p>
        {noticeLead(mode)} {hosted.notice}
      </p>
      <p>{state.status?.detail ?? `${hosted.display_name} setup is not complete.`}</p>
      <button type="button" disabled={state.busy} onClick={() => void state.connect()}>
        Continue {hosted.display_name} setup
      </button>
      <button type="button" disabled={state.busy} onClick={() => void state.check()}>
        Check {hosted.display_name}
      </button>
      {state.status?.state === 'subscription_required' && hosted.subscribe_url && (
        <button type="button" onClick={() => void state.openStore()}>
          Open subscription page
        </button>
      )}
    </>
  )
}
