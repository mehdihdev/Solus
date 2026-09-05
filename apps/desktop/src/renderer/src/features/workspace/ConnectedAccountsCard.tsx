// Home's "Connected accounts" card (SOLUSDEV-241 / I1, screen H2). OAuth binds
// at ACCOUNT scope: this is where a user links a provider account once. What
// each project tracks is chosen on that project's Sources page, whose wizard
// reuses the account here and skips the sign-in.
//
// Everything rendered is derived from the live registry (which providers use
// OAuth) and the live connection list — no provider ids in this file. Revoking
// is a confirmed, destructive action: it disconnects the account in EVERY
// project that uses it, so the confirmation names them.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { Connection } from '../../lib/api/resources'
import { ConnectWizardModal } from '../onboarding/ConnectWizardModal'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { integrationLogo } from '../onboarding/integrationLogos'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { useConnectWizard } from '../onboarding/useConnectWizard'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { revokeDetail, usageText } from './connectedAccounts'
import { ModalShell } from './modals'
import { useAccountConnections } from './useAccountConnections'

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
    setError("Couldn't revoke this account. Check your connection and try again.")
  }
  const who = connection.account_login ? ` (${connection.account_login})` : ''
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>
        Revoke {providerName}
        {who}?
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        {revokeDetail(providerName, connection)}
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" disabled={busy} onClick={() => void confirm()}>
          {busy ? 'Revoking…' : 'Revoke'}
        </Button>
      </div>
    </ModalShell>
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
  onRevoke
}: {
  entry: CatalogEntry
  connection: Connection
  onRevoke: () => Promise<boolean>
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const errored = connection.status === 'error'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 14px' }}>
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
        <div style={{ fontSize: 10.5, color: errored ? 'var(--err)' : 'var(--mut)' }}>
          {errored
            ? (connection.last_error?.message ?? 'The last sign-in failed')
            : usageText(connection)}
          {connection.access === 'write' && ' · read and edit'}
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
  const providers = catalog.filter((entry) => entry.mode === 'oauth')
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
          return (
            <div
              key={entry.id}
              style={{ borderBottom: i === providers.length - 1 ? 'none' : '1px solid var(--bd)' }}
            >
              {linked.length === 0 ? (
                <ConnectRow entry={entry} onConnect={() => wizard.open(entry)} />
              ) : (
                linked.map((connection) => (
                  <AccountRow
                    key={connection.id}
                    entry={entry}
                    connection={connection}
                    onRevoke={() => accounts.revoke(connection.id)}
                  />
                ))
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
