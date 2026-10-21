// The "connection" items under a tool's row in Home's connected-accounts card
// (SOLUSDEV-241/242/244): each linked account grant (health, quota, scope,
// confirmed Revoke, Re-authorize), each legacy project-scoped grant (Sign in
// to move / confirmed Move), and each source the current project holds for the
// tool (confirmed Disconnect). The tool's own row — mark, name, the NEXT step —
// lives in ConnectedAccountsCard; these are what already exists beneath it.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import type { Connection, LegacyConnection, Source } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { plural } from '../onboarding/selectionConfigureStep'
import { DisconnectSourceModal } from '../project/DisconnectSourceModal'
import { EditSelectionModal, type SavedChange } from '../project/EditSelectionModal'
import { HostedAddOnRow } from '../project/HostedAddOnRow'
import { LocalProjectBinding } from '../project/LocalProjectBinding'
import { sourceErrorText, sourceStatusColor, trackedIds } from '../project/sourcePresentation'
import {
  legacyText,
  moveDetail,
  reauthText,
  revokeDetail,
  healthLabel,
  quotaFraction,
  quotaNote,
  quotaText,
  scopeText,
  usageText
} from './connectedAccounts'
import { ModalShell } from './modals'
import { AccountHostedRow } from './AccountHostedRow'

/** Indented under the tool row's mark, separated from it by a hairline. */
const SUB_ROW_STYLE: React.CSSProperties = {
  padding: '10px 16px 12px 56px',
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  borderTop: '1px solid var(--bd)'
}

/** A login (or id) sits on one line and truncates instead of wrapping — a long
 *  id never pushes the item's action out of place. */
const LOGIN_STYLE: React.CSSProperties = {
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}

function ConfirmModal({
  title,
  detail,
  action,
  busyLabel,
  failure,
  danger = false,
  onClose,
  onConfirm
}: {
  title: string
  detail: string
  action: string
  busyLabel: string
  failure: string
  danger?: boolean
  onClose: () => void
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    if (await onConfirm()) {
      onClose()
      return
    }
    setBusy(false)
    setError(failure)
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        {detail}
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          kind={danger ? 'danger' : 'primary'}
          size="sm"
          disabled={busy}
          onClick={() => void confirm()}
        >
          {busy ? busyLabel : action}
        </Button>
      </div>
    </ModalShell>
  )
}

function RevokeModal({
  providerName,
  connection,
  onClose,
  onConfirm
}: {
  providerName: string
  connection: Connection
  onClose: () => void
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  const who = connection.account_login ? ` (${connection.account_login})` : ''
  return (
    <ConfirmModal
      title={`Revoke ${providerName}${who}?`}
      detail={revokeDetail(providerName, connection)}
      action="Revoke"
      busyLabel="Revoking…"
      failure="Couldn't revoke this account. Check your connection and try again."
      danger
      onClose={onClose}
      onConfirm={onConfirm}
    />
  )
}

/** The derived health, as a word (SOLUSDEV-244 / H4). Healthy stays quiet. */
function HealthBadge({ connection }: { connection: Connection }): React.JSX.Element {
  const label = healthLabel(connection)
  const color = label === 'Healthy' ? 'var(--mut)' : 'var(--warn)'
  return (
    <span
      role="status"
      aria-label={`${label}`}
      style={{
        display: 'inline-block',
        marginLeft: 8,
        fontSize: 9.5,
        fontWeight: 500,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        color,
        fontFamily: 'var(--font-mono)'
      }}
    >
      {label}
    </span>
  )
}

function QuotaLine({
  entry,
  connection
}: {
  entry: CatalogEntry
  connection: Connection
}): React.JSX.Element | null {
  const text = quotaText(connection, entry.name)
  if (!text) return null
  const fraction = quotaFraction(connection)
  const tint = connection.quota?.status === 'ok' ? 'var(--acc)' : 'var(--warn)'
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{text}</div>
      <div
        aria-hidden="true"
        style={{ height: 3, background: 'var(--bd)', borderRadius: 2, marginTop: 3, maxWidth: 220 }}
      >
        <div
          data-testid="quota-bar"
          style={{
            height: 3,
            width: `${Math.round(fraction * 100)}%`,
            background: tint,
            borderRadius: 2
          }}
        />
      </div>
    </div>
  )
}

export function AccountRow({
  entry,
  connection,
  onRevoke,
  onReauthorize
}: {
  entry: CatalogEntry
  connection: Connection
  onRevoke: () => Promise<boolean>
  onReauthorize: () => void
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const reauth = reauthText(connection)
  return (
    <div style={SUB_ROW_STYLE}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500, display: 'flex', alignItems: 'baseline' }}>
            <span style={LOGIN_STYLE} title={connection.account_login ?? undefined}>
              {connection.account_login ?? 'Linked account'}
            </span>
            <HealthBadge connection={connection} />
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            {usageText(connection)} · {scopeText(connection)}
          </div>
          <QuotaLine entry={entry} connection={connection} />
        </div>
        <Button
          kind="ghost"
          size="sm"
          aria-label={`Revoke ${entry.name}`}
          onClick={() => setConfirming(true)}
        >
          Revoke
        </Button>
      </div>
      {(reauth || entry.mode === 'oauth') && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          {reauth && (
            <div
              role="note"
              style={{ flex: 1, fontSize: 10.5, color: 'var(--warn)', lineHeight: 1.45 }}
            >
              {reauth}
            </div>
          )}
          <Button
            kind="soft"
            size="sm"
            aria-label={`Re-authorize ${entry.name}`}
            onClick={onReauthorize}
          >
            Re-authorize
          </Button>
        </div>
      )}
      {quotaNote(connection, entry.name) && (
        <div
          role="note"
          style={{ fontSize: 10.5, color: 'var(--warn)', lineHeight: 1.45 }}
          data-testid="quota-note"
        >
          {quotaNote(connection, entry.name)}
        </div>
      )}
      {confirming && (
        <RevokeModal
          providerName={entry.name}
          connection={connection}
          onClose={() => setConfirming(false)}
          onConfirm={onRevoke}
        />
      )}
      {entry.hosted && connection.status === 'connected' && (
        <AccountHostedRow key={connection.id} connectionId={connection.id} hosted={entry.hosted} />
      )}
    </div>
  )
}

export function LegacyRow({
  entry,
  legacy,
  grant,
  onSignIn,
  onMove
}: {
  entry: CatalogEntry
  legacy: LegacyConnection
  grant: Connection | null
  onSignIn: () => void
  onMove: (grant: Connection) => Promise<boolean>
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  // The move is offered only against a grant this card can NAME in the
  // confirmation — never on an id alone, so the scope shown is the scope sent.
  const claimable = grant !== null
  return (
    <div style={SUB_ROW_STYLE}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500, display: 'flex', alignItems: 'baseline' }}>
            <span style={LOGIN_STYLE} title={legacy.account_login ?? undefined}>
              {legacy.account_login ?? 'Project-scoped grant'}
            </span>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            Connected in a project, not yet on your account
          </div>
        </div>
        {claimable ? (
          <Button
            kind="primary"
            size="sm"
            aria-label={`Move ${entry.name} to your account`}
            onClick={() => setConfirming(true)}
          >
            Move to your account
          </Button>
        ) : (
          <Button
            kind="soft"
            size="sm"
            aria-label={`Sign in to move ${entry.name}`}
            onClick={onSignIn}
          >
            Sign in to move
          </Button>
        )}
      </div>
      <div role="note" style={{ fontSize: 10.5, color: 'var(--warn)', lineHeight: 1.45 }}>
        {legacyText(legacy)}
      </div>
      {confirming && grant && (
        <ConfirmModal
          title={`Move ${entry.name} to your account?`}
          detail={moveDetail(entry.name, legacy, grant)}
          action="Move"
          busyLabel="Moving…"
          failure={`Couldn't move this ${entry.name} connection. Check your connection and try again.`}
          onClose={() => setConfirming(false)}
          onConfirm={() => onMove(grant)}
        />
      )}
    </div>
  )
}

const SAVED_NOTICE_MS = 8000

/** "Edit documents · N" — only when the CONNECTOR declares a selection, per the
 *  live registry; a new connector gains the action for free. A save is
 *  acknowledged on the row while the re-sync it started runs. */
function SelectionAction({
  source,
  entry,
  projectId,
  onSaved
}: {
  source: Source
  entry: CatalogEntry
  projectId: string
  onSaved: () => void
}): React.JSX.Element | null {
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState<SavedChange | null>(null)
  // The notice acknowledges the save; the row's own sync status takes over.
  useEffect(() => {
    if (!saved) return
    const timer = setTimeout(() => setSaved(null), SAVED_NOTICE_MS)
    return () => clearTimeout(timer)
  }, [saved])
  const selection = entry.selection
  if (!selection) return null
  const tracked = trackedIds(source, selection.config_key)
  const noun = plural(selection.label)
  return (
    <>
      <Button
        kind="ghost"
        size="sm"
        aria-label={`Edit ${noun} for ${source.name}`}
        onClick={() => {
          setSaved(null)
          setEditing(true)
        }}
      >
        Edit {noun} · {tracked.length}
      </Button>
      {saved && (
        <span role="status" style={{ fontSize: 10.5, color: 'var(--ok)' }}>
          Selection saved · added {saved.added}, removed {saved.removed} · syncing
        </span>
      )}
      {editing && (
        <EditSelectionModal
          projectId={projectId}
          sourceId={source.id}
          sourceName={source.name}
          selection={selection}
          current={tracked}
          onClose={() => setEditing(false)}
          onSaved={(change) => {
            setSaved(change)
            onSaved()
          }}
        />
      )}
    </>
  )
}

/** One source the current project holds for this tool (a committed export, a
 *  picked document set, …): status, last sync, Sync now, its selection, its
 *  hosted add-on when the connector carries one, and a confirmed Disconnect. */
export function SourceItem({
  source,
  entry,
  projectId,
  onSync,
  onDisconnect,
  onChanged
}: {
  source: Source
  entry: CatalogEntry
  projectId: string
  onSync: () => void
  onDisconnect: () => Promise<boolean>
  onChanged: () => void
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  return (
    <div style={SUB_ROW_STYLE}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <SourceSummary source={source} />
        <Button kind="ghost" size="sm" aria-label={`Sync ${source.name} now`} onClick={onSync}>
          <Icons.play size={11} /> Sync now
        </Button>
        <SelectionAction source={source} entry={entry} projectId={projectId} onSaved={onChanged} />
        {entry.configFields.includes('project_path') && (
          <LocalProjectBinding
            key={`${projectId}:${source.id}`}
            projectId={projectId}
            source={source}
            onSaved={onChanged}
          />
        )}
        <Button
          kind="ghost"
          size="sm"
          aria-label={`Disconnect ${source.name}`}
          onClick={() => setConfirming(true)}
        >
          Disconnect
        </Button>
      </div>
      {/* An add-on rides an existing grant: offered only on a CONNECTED source. */}
      {entry.hosted && source.status === 'connected' && (
        <HostedAddOnRow
          source={source}
          projectId={projectId}
          hosted={entry.hosted}
          providerName={entry.name}
          onChanged={onChanged}
        />
      )}
      {confirming && (
        <DisconnectSourceModal
          name={source.name}
          onClose={() => setConfirming(false)}
          onConfirm={onDisconnect}
        />
      )}
    </div>
  )
}

function SourceSummary({ source }: { source: Source }): React.JSX.Element {
  const count = source.entity_count
  const synced = source.last_synced_at
    ? `synced ${relativeTime(source.last_synced_at)}`
    : 'never synced'
  const errorText = sourceErrorText(source.last_error)
  return (
    <div style={{ flex: 1, minWidth: 160 }}>
      <div style={{ fontSize: 12, fontWeight: 500, ...LOGIN_STYLE }} title={source.name}>
        {source.name}
      </div>
      <div style={{ fontSize: 10.5, color: 'var(--mut)', display: 'flex', gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: 99,
            background: sourceStatusColor(source.status),
            alignSelf: 'center',
            flexShrink: 0
          }}
        />
        <span>
          {source.status} · {synced}
          {typeof count === 'number' && ` · ${count} entities`}
        </span>
      </div>
      {errorText && (
        <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 2 }}>{errorText}</div>
      )}
    </div>
  )
}
