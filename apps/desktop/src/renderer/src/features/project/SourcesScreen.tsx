// Per-project Sources page (SOLUSDEV-164). The add/remove/select integration
// surface missing after onboarding: it lists the tools connected to the open
// project with per-source Sync and Disconnect actions, and a "Connect a tool"
// catalog whose tiles open the connect wizard (SOLUSDEV-165) — the same REAL
// flows as onboarding (GitHub OAuth, KiCad/Altium committed-export file pick —
// SOLUSDEV-103/-100), one implementation. Disconnect RETAINS already-synced
// graph data (the source's entities are orphaned into manual nodes, not
// deleted); a signed-in user can always connect, so the guard is "project
// selected + fetch enabled", not the onboarding `linked` flag.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { ModalShell } from '../workspace/modals'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { ConnectCatalog } from '../onboarding/ConnectCatalog'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { plural } from '../onboarding/selectionConfigureStep'
import { EditSelectionModal } from './EditSelectionModal'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { sourceErrorText, sourceStatusColor, sourceTypeLabel } from './sourcePresentation'
import { useProjectSources } from './useProjectSources'
import { LocalConnectionsSection } from './localconnections/LocalConnectionsSection'

/** What a source tracks today, read from its own config under the connector's
 *  declared key. A single-select connector stores a scalar, multi stores a list. */
function trackedIds(source: Source, configKey?: string): string[] {
  if (!configKey) return []
  const value = (source.config as Record<string, unknown> | undefined)?.[configKey]
  if (Array.isArray(value)) return value.filter((v): v is string => typeof v === 'string')
  return typeof value === 'string' ? [value] : []
}

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
          <ConnectedList sources={data.sources} actions={data.actions} projectId={projectId} />
        )}

        <ConnectPanel projectId={projectId} onConnected={() => void data.actions.refresh()} />

        {/* Local streams (simulators, serial devices, bridge tools) — SOLUSDEV-72. */}
        <LocalConnectionsSection projectId={projectId} />
      </div>
    </div>
  )
}

function ConnectedList({
  sources,
  actions,
  projectId
}: {
  sources: Source[]
  actions: ReturnType<typeof useProjectSources>['actions']
  projectId: string
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
              projectId={projectId}
              last={i === sources.length - 1}
              onSync={() => void actions.syncNow(s.id)}
              onDisconnect={() => actions.disconnect(s.id)}
              onSelectionSaved={() => void actions.refresh()}
            />
          ))}
        </Card>
      )}
    </>
  )
}

/** "Choose documents…" — shown only when the CONNECTOR declares a selection, per
 *  the live registry. No provider check appears here, so a new connector gains
 *  the action for free. */
function SelectionAction({
  source,
  projectId,
  onSaved
}: {
  source: Source
  projectId: string
  onSaved: () => void
}): React.JSX.Element | null {
  const [editing, setEditing] = useState(false)
  const selection = useIntegrationCatalog().find((e) => e.id === source.type)?.selection ?? null
  if (!selection) return null

  return (
    <>
      <Button
        kind="ghost"
        size="sm"
        aria-label={`Choose ${plural(selection.label)} for ${source.name}`}
        onClick={() => setEditing(true)}
      >
        {plural(selection.label)}
      </Button>
      {editing && (
        <EditSelectionModal
          projectId={projectId}
          sourceId={source.id}
          sourceName={source.name}
          selection={selection}
          current={trackedIds(source, selection.config_key)}
          onClose={() => setEditing(false)}
          onSaved={onSaved}
        />
      )}
    </>
  )
}

function SourceRow({
  source,
  projectId,
  last,
  onSync,
  onDisconnect,
  onSelectionSaved
}: {
  source: Source
  projectId: string
  last: boolean
  onSync: () => void
  onDisconnect: () => Promise<boolean>
  onSelectionSaved: () => void
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const synced = source.last_synced_at
    ? `Synced ${relativeTime(source.last_synced_at)}`
    : 'Never synced'
  // WHICH account this source is connected as. Providers differ in how much
  // they will tell us: GitHub gives a login, Onshape under its read-only scope
  // gives only an opaque account id. Show whichever is real and never invent
  // one — an unlabelled source is more honest than a fabricated name.
  const account = source.account_login?.trim() || null
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
          {sourceTypeLabel(source.type)}
          {account && ` · ${account}`} · {synced}
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
      <SelectionAction source={source} projectId={projectId} onSaved={onSelectionSaved} />
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

/** The "Connect a tool" catalog — the shared wizard-driven connect surface. */
function ConnectPanel({
  projectId,
  onConnected
}: {
  projectId: string
  onConnected: () => void
}): React.JSX.Element {
  // Clear any stale connect-tile state carried over from onboarding so this
  // page starts from the live source list, not a previous session's tiles.
  useEffect(() => {
    useOnboardingStore.getState().reset()
  }, [])

  return (
    <>
      <SectionLabel>CONNECT A TOOL</SectionLabel>
      <ConnectCatalog projectId={projectId} onConnected={onConnected} />
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
