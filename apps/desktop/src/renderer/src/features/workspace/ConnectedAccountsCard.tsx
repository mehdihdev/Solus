// Home's "Connected accounts" card (SOLUSDEV-241 / I1, screen H2). OAuth binds
// at ACCOUNT scope: this is where a user links a provider account once. What
// each project tracks is chosen on that project's Sources page, whose wizard
// reuses the account here and skips the sign-in.
//
// Everything rendered is derived from the live registry (which providers use
// OAuth) and the live connection list — no provider ids in this file. Revoking
// is a confirmed, destructive action: it disconnects the account in EVERY
// project that uses it, so the confirmation names them.
//
// SOLUSDEV-242 (H2): every linked row states its SCOPE plainly (read only /
// read and edit / not recorded); a grant whose last sign-in failed offers
// Re-authorize, which lands on the same account (no duplicate, no widened
// scope; the old token keeps working until the new one succeeds); a
// project-scoped grant from before account-level connections is listed as
// "sign in once to move it"; once the user holds the proving grant the row
// offers the move as an explicit, confirmed action naming the projects and the
// grant — never a side effect of loading Home.
// Every catalog tool appears: file-export and local tools have no account to
// link, and the row says where they connect instead.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { Connection, LegacyConnection } from '../../lib/api/resources'
import { ConnectWizardModal } from '../onboarding/ConnectWizardModal'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { integrationLogo } from '../onboarding/integrationLogos'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { useConnectWizard } from '../onboarding/useConnectWizard'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import {
  legacyText,
  moveDetail,
  reauthText,
  revokeDetail,
  scopeText,
  usageText
} from './connectedAccounts'
import { ModalShell } from './modals'
import { useAccountConnections } from './useAccountConnections'

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

function ProviderMark({ entry }: { entry: CatalogEntry }): React.JSX.Element {
  const logo = integrationLogo(entry.id)
  return (
    <span
      aria-hidden
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        flexShrink: 0
      }}
    >
      {logo ? (
        <img src={logo} alt="" style={{ width: 18, height: 18, objectFit: 'contain' }} />
      ) : (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{entry.mark}</span>
      )}
    </span>
  )
}

function AccountRow({
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
    <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <ProviderMark entry={entry} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>
            {entry.name}
            {connection.account_login && (
              <span style={{ fontWeight: 400, color: 'var(--mut)' }}>
                {' '}
                · {connection.account_login}
              </span>
            )}
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            {usageText(connection)} · {scopeText(connection)}
          </div>
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
      {reauth && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <div
            role="note"
            style={{ flex: 1, fontSize: 10.5, color: 'var(--warn)', lineHeight: 1.45 }}
          >
            {reauth}
          </div>
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
      {confirming && (
        <RevokeModal
          providerName={entry.name}
          connection={connection}
          onClose={() => setConfirming(false)}
          onConfirm={onRevoke}
        />
      )}
    </div>
  )
}

/** A grant still owned by a project: a sign-in proves the account; once the
 *  caller holds that grant, the move is offered and confirmed here. */
function LegacyRow({
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
  onMove: () => Promise<boolean>
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const claimable = legacy.claimable_connection_id !== null
  return (
    <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <ProviderMark entry={entry} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>
            {entry.name}
            {legacy.account_login && (
              <span style={{ fontWeight: 400, color: 'var(--mut)' }}>
                {' '}
                · {legacy.account_login}
              </span>
            )}
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
      {confirming && (
        <ConfirmModal
          title={`Move ${entry.name} to your account?`}
          detail={moveDetail(entry.name, legacy, grant)}
          action="Move"
          busyLabel="Moving…"
          failure={`Couldn't move this ${entry.name} connection. Check your connection and try again.`}
          onClose={() => setConfirming(false)}
          onConfirm={onMove}
        />
      )}
    </div>
  )
}

/** A tool with no account to link: it connects per project (a committed export
 *  or the local companion), so the row says so instead of pretending. */
function NoAccountRow({ entry }: { entry: CatalogEntry }): React.JSX.Element {
  const where =
    entry.mode === 'local-bridge'
      ? "Connects on this computer from a project's Sources page — no account to link"
      : "Connects from a project's Sources page as a committed export — no account to link"
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 14px' }}>
      <ProviderMark entry={entry} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{entry.name}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{where}</div>
      </div>
      <Mono size={8.5} color="var(--mut)">
        PER PROJECT
      </Mono>
    </div>
  )
}

function ConnectRow({
  entry,
  onConnect
}: {
  entry: CatalogEntry
  onConnect: () => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 14px' }}>
      <ProviderMark entry={entry} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{entry.name}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>Not connected</div>
      </div>
      <Button kind="ghost" size="sm" aria-label={`Connect ${entry.name}`} onClick={onConnect}>
        Connect
      </Button>
    </div>
  )
}

export function ConnectedAccountsCard(): React.JSX.Element | null {
  const catalog = useIntegrationCatalog()
  const accounts = useAccountConnections()
  const states = useOnboardingStore((s) => s.connections)
  const wizard = useConnectWizard({
    projectId: null,
    scope: 'account',
    onConnected: () => void accounts.refresh()
  })
  // Every tool the registry knows, account or not — the user asked "what can I
  // connect?", and a missing row reads as "unsupported". Account tools first;
  // the per-project ones follow so the linkable rows read as one group.
  const providers = [...catalog].sort(
    (a, b) => Number(b.mode === 'oauth') - Number(a.mode === 'oauth')
  )
  if (accounts.status === 'offline' || providers.length === 0) return null

  return (
    <div>
      <div style={{ margin: '0 0 10px' }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          CONNECTED ACCOUNTS
        </Mono>
      </div>
      <Card pad={0}>
        {providers.map((entry, i) => {
          const linked = accounts.connections.filter((c) => c.provider === entry.id)
          const unclaimed = accounts.legacy.filter((l) => l.provider === entry.id)
          return (
            <div
              key={entry.id}
              style={{ borderBottom: i === providers.length - 1 ? 'none' : '1px solid var(--bd)' }}
            >
              {entry.mode !== 'oauth' ? (
                <NoAccountRow entry={entry} />
              ) : (
                <>
                  {linked.map((connection) => (
                    <AccountRow
                      key={connection.id}
                      entry={entry}
                      connection={connection}
                      onRevoke={() => accounts.revoke(connection.id)}
                      // The same account-scope handshake as Connect: a finished
                      // sign-in lands on THIS row (I1 dedupes by account), so the
                      // old token is replaced only once the new one succeeded.
                      onReauthorize={() => wizard.open(entry)}
                    />
                  ))}
                  {unclaimed.map((legacy) => (
                    <LegacyRow
                      key={legacy.source_ids.join(',')}
                      entry={entry}
                      legacy={legacy}
                      grant={linked.find((c) => c.id === legacy.claimable_connection_id) ?? null}
                      // The sign-in proves the account; the move is then offered
                      // and confirmed on this row — never automatic.
                      onSignIn={() => wizard.open(entry)}
                      onMove={() => accounts.move(legacy)}
                    />
                  ))}
                  {linked.length === 0 && unclaimed.length === 0 && (
                    <ConnectRow entry={entry} onConnect={() => wizard.open(entry)} />
                  )}
                </>
              )}
            </div>
          )
        })}
      </Card>
      <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.5 }}>
        Link an account once; choose what each project tracks from its Sources page.
      </div>
      {wizard.active && (
        <ConnectWizardModal
          entry={wizard.active}
          scope="account"
          state={states[wizard.active.id]}
          onBegin={() => void wizard.begin()}
          onPickFile={(file) => void wizard.pickFile(file)}
          onSelect={wizard.select}
          onSubmitConfig={wizard.submitConfig}
          onChooseAccess={wizard.chooseAccess}
          onClose={wizard.close}
        />
      )}
    </div>
  )
}
