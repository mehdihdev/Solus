// Home's "Connected accounts" card (SOLUSDEV-241 / I1, screen H2), grouped by
// domain (SOLUSDEV-244). ONE flow for every tool, whatever it is:
//
//   [mark] Tool name                                   [ next step ]
//          status line
//          ─ what already exists: accounts / sources / sessions, each with
//            its own confirmed action (Revoke · Disconnect · Stop)
//
// The next step is always offered — a tool with a linked account or an
// existing source still takes another — and every step runs through the
// connect wizard modal (ConnectWizardModal): account sign-in for OAuth tools,
// then "Pick documents" on the open project reusing that account; "Choose
// file" for committed-export tools; the registry's own guidance for local
// tools; and Start for simulators (SimulationPanel, same visual language).
// Everything rendered is derived from the live registry and live lists — no
// provider ids in this file; a new connector gets a correct row for free.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { BridgeStatus, Source } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { ConnectWizardModal } from '../onboarding/ConnectWizardModal'
import type { WizardScope } from '../onboarding/connectSteps'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { integrationLogo } from '../onboarding/integrationLogos'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { plural } from '../onboarding/selectionConfigureStep'
import { useConnectWizard } from '../onboarding/useConnectWizard'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { toolStatusText } from '../project/localconnections/presentation'
import { useProjectSources } from '../project/useProjectSources'
import { AccountRow, LegacyRow, SourceItem } from './AccountRows'
import {
  ACCOUNT_DOMAINS,
  ACCOUNT_DOMAIN_LABEL,
  NEEDS_PROJECT_HINT,
  accountDomain,
  emptyDomainText,
  type AccountDomain
} from './accountDomains'
import { SimulationPanel } from './SimulationPanel'
import { linkedAccountFor, useAccountConnections } from './useAccountConnections'
import { useBridgeStatus } from './useBridgeStatus'

/** The square mark every row (and the simulator rows) leads with. */
export function ProviderMark({
  entry
}: {
  entry: Pick<CatalogEntry, 'id' | 'mark'>
}): React.JSX.Element {
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

/** The standard row head: mark, name, one status line, and the next step. */
export function ToolRowHead({
  entry,
  status,
  action,
  actionLabel,
  disabledHint,
  onAction
}: {
  entry: Pick<CatalogEntry, 'id' | 'name' | 'mark'>
  status: string
  action: string
  /** Accessible name; defaults to `${action} ${entry.name}`. */
  actionLabel?: string
  /** Non-null disables the action and says why beneath the status line. */
  disabledHint?: string | null
  onAction: () => void
}): React.JSX.Element {
  const disabled = disabledHint != null
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '13px 16px' }}>
      <ProviderMark entry={entry} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{entry.name}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{status}</div>
        {disabled && (
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }} data-testid="needs-project">
            {disabledHint}
          </div>
        )}
      </div>
      <Button
        kind={disabled ? 'ghost' : 'primary'}
        size="sm"
        aria-label={actionLabel ?? `${action} ${entry.name}`}
        disabled={disabled}
        onClick={onAction}
      >
        {action}
      </Button>
    </div>
  )
}

interface NextStep {
  action: string
  scope: WizardScope
  needsProject: boolean
}

/** What the tool's row offers next — derived from the connector's declared
 *  shape and whether an account is already linked, never from its id. */
function nextStep(entry: CatalogEntry, linked: boolean): NextStep {
  if (entry.mode === 'export-file')
    return { action: 'Choose file', scope: 'project', needsProject: true }
  if (entry.mode === 'local-bridge')
    return { action: 'Connect', scope: 'project', needsProject: false }
  if (!linked) return { action: 'Connect', scope: 'account', needsProject: false }
  const action = entry.selection
    ? `Pick ${plural(entry.selection.label)}`
    : entry.configFields.length > 0
      ? 'Enter details'
      : 'Add to project'
  return { action, scope: 'project', needsProject: true }
}

function statusLine(
  entry: CatalogEntry,
  linkedCount: number,
  sources: readonly Source[],
  project: WorkspaceProject | null,
  bridge: BridgeStatus | null
): string {
  const here = project ? ` in ${project.name}` : ''
  const held = sources.length > 0 ? ` · ${sources.length} connected${here}` : ''
  if (entry.mode === 'local-bridge' && entry.localTool) {
    return toolStatusText(entry.localTool, bridge)
  }
  if (entry.mode === 'export-file') return `Committed export · per project${held}`
  if (linkedCount === 0) return 'Not connected'
  return `${linkedCount} account${linkedCount === 1 ? '' : 's'} linked${held}`
}

interface ToolRowProps {
  entry: CatalogEntry
  accounts: ReturnType<typeof useAccountConnections>
  sources: ReturnType<typeof useProjectSources>
  currentProject: WorkspaceProject | null
  bridge: BridgeStatus | null
  onOpen: (entry: CatalogEntry, scope: WizardScope) => void
}

/** One tool: its head, then everything that already exists for it. */
function ToolRow({
  entry,
  accounts,
  sources,
  currentProject,
  bridge,
  onOpen
}: ToolRowProps): React.JSX.Element {
  const linked = accounts.connections.filter((c) => c.provider === entry.id)
  const unclaimed = accounts.legacy.filter((l) => l.provider === entry.id)
  const held = sources.sources.filter((s) => s.type === entry.id)
  const step = nextStep(entry, linkedAccountFor(accounts.connections, entry.id) !== null)
  const disabledHint = step.needsProject && !currentProject ? NEEDS_PROJECT_HINT : null
  return (
    <div>
      <ToolRowHead
        entry={entry}
        status={statusLine(entry, linked.length, held, currentProject, bridge)}
        action={step.action}
        actionLabel={`${step.action} for ${entry.name}`}
        disabledHint={disabledHint}
        onAction={() => onOpen(entry, step.scope)}
      />
      {linked.map((connection) => (
        <AccountRow
          key={connection.id}
          entry={entry}
          connection={connection}
          onRevoke={() => accounts.revoke(connection.id)}
          // The same account-scope handshake as Connect: a finished sign-in
          // lands on THIS grant (I1 dedupes by account), so the old token is
          // replaced only once the new one succeeded.
          onReauthorize={() => onOpen(entry, 'account')}
        />
      ))}
      {unclaimed.map((legacy) => (
        <LegacyRow
          key={legacy.source_ids.join(',')}
          entry={entry}
          legacy={legacy}
          grant={linked.find((c) => c.id === legacy.claimable_connection_id) ?? null}
          // The sign-in proves the account; the move is then offered and
          // confirmed on this item — never automatic.
          onSignIn={() => onOpen(entry, 'account')}
          onMove={(grant) => accounts.move(legacy, grant)}
        />
      ))}
      {held.map((source) => (
        <SourceItem
          key={source.id}
          source={source}
          entry={entry}
          projectId={source.project_id}
          onSync={() => void sources.actions.syncNow(source.id)}
          onDisconnect={() => sources.actions.disconnect(source.id)}
          onChanged={() => void sources.actions.refresh()}
        />
      ))}
    </div>
  )
}

/** The domain pills above the card: one selected, the rest quiet. */
function DomainTabs({
  value,
  onChange
}: {
  value: AccountDomain
  onChange: (domain: AccountDomain) => void
}): React.JSX.Element {
  return (
    <div
      role="tablist"
      aria-label="Tool domain"
      style={{ display: 'flex', gap: 8, margin: '0 0 10px' }}
    >
      {ACCOUNT_DOMAINS.map((domain) => {
        const active = domain === value
        return (
          <button
            key={domain}
            type="button"
            role="tab"
            aria-selected={active}
            id={`accounts-tab-${domain}`}
            className="interactive"
            onClick={() => onChange(domain)}
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 11.5,
              fontWeight: active ? 600 : 500,
              padding: '5px 13px',
              borderRadius: 99,
              cursor: 'pointer',
              userSelect: 'none',
              whiteSpace: 'nowrap',
              background: active ? 'var(--acc)' : 'var(--sur2)',
              color: active ? 'var(--acc-ink)' : 'var(--mut)',
              border: `1px solid ${active ? 'transparent' : 'var(--bd)'}`,
              transition: 'background 0.12s, color 0.12s, border-color 0.12s'
            }}
          >
            {ACCOUNT_DOMAIN_LABEL[domain]}
          </button>
        )
      })}
    </div>
  )
}

export interface ConnectedAccountsCardProps {
  /** The current project: where a picked document set, a chosen file, or a
   *  simulation lands. Null ⇒ project-bound steps are offered but disabled. */
  currentProject?: WorkspaceProject | null
}

export function ConnectedAccountsCard({
  currentProject = null
}: ConnectedAccountsCardProps = {}): React.JSX.Element | null {
  const catalog = useIntegrationCatalog()
  const accounts = useAccountConnections()
  const sources = useProjectSources()
  const bridge = useBridgeStatus(currentProject?.id ?? null)
  const states = useOnboardingStore((s) => s.connections)
  const [domain, setDomain] = useState<AccountDomain>(ACCOUNT_DOMAINS[0])
  // One wizard, two scopes: the account sign-in, or a project-bound step that
  // reuses the linked account (the rail then skips the sign-in).
  const [scope, setScope] = useState<WizardScope>('account')
  const wizard = useConnectWizard({
    projectId: currentProject?.id ?? null,
    scope,
    linkedConnections: accounts.connections,
    onConnected: () => {
      void accounts.refresh()
      void sources.actions.refresh()
    }
  })
  const open = (entry: CatalogEntry, nextScope: WizardScope): void => {
    setScope(nextScope)
    wizard.open(entry)
  }
  // Every tool the registry knows, account or not — a missing row reads as
  // "unsupported". Within a domain the account tools come first.
  const providers = catalog
    .filter((entry) => accountDomain(entry) === domain)
    .sort((a, b) => Number(b.mode === 'oauth') - Number(a.mode === 'oauth'))
  if (accounts.status === 'offline' || catalog.length === 0) return null

  return (
    <div>
      <div style={{ margin: '0 0 10px' }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          CONNECTED ACCOUNTS
        </Mono>
      </div>
      <DomainTabs value={domain} onChange={setDomain} />
      <Card pad={0}>
        {/* Keyed by domain so each switch remounts the panel and replays the entrance. */}
        <div
          key={domain}
          role="tabpanel"
          aria-labelledby={`accounts-tab-${domain}`}
          className="accounts-panel-in"
        >
          {domain === 'simulation' && <SimulationPanel currentProject={currentProject} />}
          {domain !== 'simulation' && providers.length === 0 && (
            <div style={{ padding: '14px', fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
              {emptyDomainText(domain)}
            </div>
          )}
          {providers.map((entry, i) => (
            <div
              key={entry.id}
              style={{ borderBottom: i === providers.length - 1 ? 'none' : '1px solid var(--bd)' }}
            >
              <ToolRow
                entry={entry}
                accounts={accounts}
                sources={sources}
                currentProject={currentProject}
                bridge={bridge}
                onOpen={open}
              />
            </div>
          ))}
        </div>
      </Card>
      {wizard.active && (
        <ConnectWizardModal
          entry={wizard.active}
          scope={scope}
          state={states[wizard.active.id]}
          linkedAccount={
            wizard.linkedAccount ? { login: wizard.linkedAccount.account_login } : null
          }
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
