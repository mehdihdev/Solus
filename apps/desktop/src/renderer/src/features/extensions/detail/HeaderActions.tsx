// SOLUSDEV-235 — the detail header's action cluster: Update / Enable / Uninstall
// for an install, Install (with its gate) otherwise.
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import type { ExtensionView } from '../extension.types'
import type { ExtensionActions } from '../extensionActions'
import { requirementLabel } from '../extensionLogic'
import type { InstallFlow } from './useInstallFlow'

export function HeaderActions({
  view,
  actions,
  flow,
  onUninstall
}: {
  view: ExtensionView
  actions: ExtensionActions
  flow: InstallFlow
  onUninstall: () => void
}): React.JSX.Element {
  const { catalog, state } = view
  if (state.installed) {
    const update = state.updateAvailable
    return (
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        {update && (
          <Button
            kind="primary"
            size="sm"
            disabled={flow.busy}
            onClick={() => void flow.beginUpdate()}
          >
            {flow.busy && !flow.step ? 'Updating…' : `Update to ${update.version}`}
          </Button>
        )}
        <Button
          kind="soft"
          size="sm"
          onClick={() => void actions.setEnabled(catalog.slug, !state.enabled)}
        >
          {state.enabled ? 'Disable' : 'Enable'}
        </Button>
        <Button kind="danger" size="sm" onClick={onUninstall}>
          Uninstall
        </Button>
      </div>
    )
  }
  return <InstallGate view={view} onInstall={flow.beginInstall} />
}

function InstallGate({
  view,
  onInstall
}: {
  view: ExtensionView
  onInstall: () => void
}): React.JSX.Element {
  const needsSource = view.availability === 'needs_source'
  const blocked = view.availability === 'blocked'
  const loading = view.manifest === null
  const title = blocked
    ? 'Blocked by your team'
    : needsSource
      ? 'Connect a required source first'
      : loading
        ? 'Loading the extension’s manifest…'
        : undefined
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexShrink: 0 }}>
      {needsSource && (
        <Mono size={9.5} color="var(--mut)">
          NEEDS {requirementLabel(view.missing)}
        </Mono>
      )}
      {blocked && <span style={{ fontSize: 12, color: 'var(--mut)' }}>Blocked by your team</span>}
      <Button
        kind="primary"
        size="sm"
        disabled={needsSource || blocked || loading}
        title={title}
        onClick={onInstall}
      >
        Install
      </Button>
    </div>
  )
}
