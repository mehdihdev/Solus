// Per-project Sources page (SOLUSDEV-164). The add/remove/select integration
// surface missing after onboarding: it lists the tools connected to the open
// project with per-source Sync and Disconnect actions, and a "Connect a tool"
// catalog that reuses the REAL onboarding connect flows (GitHub OAuth, KiCad/
// Altium committed-export file pick — SOLUSDEV-103/-100). Disconnect RETAINS
// already-synced graph data (the source's entities are orphaned into manual
// nodes, not deleted); a signed-in user can always connect, so the guard is
// "project selected + fetch enabled", not the onboarding `linked` flag.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { ModalShell } from '../workspace/modals'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { ConnectTile } from '../onboarding/ConnectTile'
import { type CatalogEntry } from '../onboarding/integrationCatalog'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { useGithubConnect } from '../onboarding/useGithubConnect'
import { useEdaConnect } from '../onboarding/useEdaConnect'
import { sourceErrorText, sourceStatusColor, sourceTypeLabel } from './sourcePresentation'
import { useProjectSources } from './useProjectSources'

const EXPORT_FILE_ACCEPT = '.xml,.net'
const NO_BRIDGE_ERROR = 'GitHub connect needs the Solus desktop app.'

export function SourcesScreen(): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  if (!project) {
    return (
      <ScreenEmptyState
        icon={<Icons.link size={30} />}
        title="Select a project"
        body="Open a project from Home to connect and manage its tools."
      />
    )
  }
  return <SourcesView projectId={project.id} />
}

function SourcesView({ projectId }: { projectId: string }): React.JSX.Element {
  const data = useProjectSources()
  const reason = useOfflineReason()

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '26px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Sources
        </h1>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
          The tools feeding this project&apos;s context model. Each source becomes a domain in the
          graph.
        </div>

        {data.status === 'offline' ? (
          <Card pad={16} style={{ marginTop: 20 }}>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
              {reason === 'api_unreachable'
                ? "Solus can't reach its API right now — connected sources will list here once the backend is reachable."
                : 'Sign in to Solus to connect and manage this project’s tools.'}
            </div>
          </Card>
        ) : (
          <ConnectedList sources={data.sources} actions={data.actions} />
        )}

        <ConnectPanel projectId={projectId} onConnected={() => void data.actions.refresh()} />
      </div>
    </div>
  )
}

function ConnectedList({
  sources,
  actions
}: {
  sources: Source[]
  actions: ReturnType<typeof useProjectSources>['actions']
}): React.JSX.Element {
  return (
    <>
      <SectionLabel>CONNECTED SOURCES</SectionLabel>
      {sources.length === 0 ? (
        <Card pad={20}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            No tools connected yet. Connect one below to start building the graph.
          </div>
        </Card>
      ) : (
        <Card pad={0}>
          {sources.map((s, i) => (
            <SourceRow
              key={s.id}
              source={s}
              last={i === sources.length - 1}
              onSync={() => void actions.syncNow(s.id)}
              onDisconnect={() => actions.disconnect(s.id)}
            />
          ))}
        </Card>
      )}
    </>
  )
}

function SourceRow({
  source,
  last,
  onSync,
  onDisconnect
}: {
  source: Source
  last: boolean
  onSync: () => void
  onDisconnect: () => Promise<boolean>
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const synced = source.last_synced_at
    ? `Synced ${relativeTime(source.last_synced_at)}`
    : 'Never synced'
  const entities =
    typeof source.entity_count === 'number' ? ` · ${source.entity_count} entities` : ''
  const errorText = sourceErrorText(source.last_error)

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '13px 16px',
        borderBottom: last ? 'none' : '1px solid var(--bd)'
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: 99,
          background: sourceStatusColor(source.status),
          flexShrink: 0
        }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{source.name}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
          {sourceTypeLabel(source.type)} · {synced}
          {entities}
        </div>
        {errorText && (
          <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 2 }}>{errorText}</div>
        )}
      </div>
      <Mono size={8.5} color="var(--mut)">
        {source.status.toUpperCase()}
      </Mono>
      <Button kind="ghost" size="sm" onClick={onSync}>
        <Icons.play size={11} /> Sync now
      </Button>
      <Button
        kind="ghost"
        size="sm"
        aria-label={`Disconnect ${source.name}`}
        onClick={() => setConfirming(true)}
      >
        Disconnect
      </Button>
      {confirming && (
        <DisconnectModal
          name={source.name}
          onClose={() => setConfirming(false)}
          onConfirm={onDisconnect}
        />
      )}
    </div>
  )
}

function DisconnectModal({
  name,
  onClose,
  onConfirm
}: {
  name: string
  onClose: () => void
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const ok = await onConfirm()
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError("Couldn't disconnect this source. Check your access and try again.")
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Disconnect {name}?</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Stops syncing this tool. Solus keeps the entities it has already contributed to your graph,
        and you can reconnect it anytime.
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" disabled={busy} onClick={() => void confirm()}>
          {busy ? 'Disconnecting…' : 'Disconnect'}
        </Button>
      </div>
    </ModalShell>
  )
}

/** The "Connect a tool" catalog — reuses the real onboarding connect flows. */
function ConnectPanel({
  projectId,
  onConnected
}: {
  projectId: string
  onConnected: () => void
}): React.JSX.Element {
  const catalog = useIntegrationCatalog()
  const connections = useOnboardingStore((s) => s.connections)
  const failConnect = useOnboardingStore((s) => s.failConnect)
  const github = useGithubConnect()
  const eda = useEdaConnect()
  const exportInput = useRef<HTMLInputElement | null>(null)
  const pendingProvider = useRef<string | null>(null)

  // Clear any stale connect-tile state carried over from onboarding so this
  // page starts from the live source list, not a previous session's tiles.
  useEffect(() => {
    useOnboardingStore.getState().reset()
  }, [])

  const connect = (integ: CatalogEntry): void => {
    if (integ.mode === 'github-oauth') {
      if (!getDesktopOAuthBridge()) {
        failConnect(integ.id, NO_BRIDGE_ERROR)
        return
      }
      void github.start(projectId).then(onConnected)
      return
    }
    pendingProvider.current = integ.id
    exportInput.current?.click()
  }

  const onExportPicked = async (input: HTMLInputElement): Promise<void> => {
    const provider = pendingProvider.current
    pendingProvider.current = null
    const file = input.files?.[0]
    input.value = ''
    if (!provider || !file) return
    const content = await file.text()
    await eda.start(projectId, provider, { fileName: file.name, content })
    onConnected()
  }

  return (
    <>
      <SectionLabel>CONNECT A TOOL</SectionLabel>
      <input
        ref={exportInput}
        type="file"
        accept={EXPORT_FILE_ACCEPT}
        aria-label="Choose a committed netlist export"
        style={{ display: 'none' }}
        onChange={(e) => void onExportPicked(e.currentTarget)}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {catalog.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onConnect={() => connect(integ)}
            onChooseRepo={github.chooseRepo}
            onRetry={() => connect(integ)}
          />
        ))}
      </div>
      {catalog.length === 0 && (
        <Card pad={16}>
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>
            No connectors are available to add right now.
          </div>
        </Card>
      )}
    </>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ margin: '24px 0 10px' }}>
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        {children}
      </Mono>
    </div>
  )
}
