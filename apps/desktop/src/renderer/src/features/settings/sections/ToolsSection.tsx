// Settings › Connected tools (SOLUSDEV-318, replaces the SOLUSDEV-86
// integrations catalog): the user's ACCOUNT-scoped grants (SOLUSDEV-241,
// GET /users/me/connections) with their real health, so Settings answers "is
// my Onshape still linked?" — and one way out to Home › Connected accounts,
// where linking, revoking and the Onshape panel pairing live.
import { Button } from '../../../components/ui/Button'
import { useIntegrationCatalog } from '../../onboarding/useIntegrationCatalog'
import { ProviderMark } from '../../workspace/ConnectedAccountsCard'
import { settingsStagger } from '../settingsMotion'
import { Section, StatusTag } from '../settingsUi'
import { connectionHealth } from '../connectionHealth'
import type { Connection } from '../../../lib/api/resources'
import type { AccountConnectionsStatus } from '../../workspace/useAccountConnections'

function detailLine(c: Connection): string {
  const who = c.account_login ? `@${c.account_login}` : 'Linked account'
  const n = c.projects.length
  return `${who} · used in ${n} project${n === 1 ? '' : 's'}`
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function ToolRow({
  connection,
  name,
  mark
}: {
  connection: Connection
  name: string
  mark: string
}): React.JSX.Element {
  const health = connectionHealth(connection)
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      {/* Home's own mark: the bundled brand logo, letter mark as fallback. */}
      <ProviderMark entry={{ id: connection.provider, mark }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{name}</div>
        <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{detailLine(connection)}</div>
      </div>
      <StatusTag tone={health.tone}>{health.label}</StatusTag>
    </div>
  )
}

export interface ToolsSectionProps {
  status: AccountConnectionsStatus
  connections: readonly Connection[]
  /** Home › Connected accounts. */
  onManage: () => void
}

const MUTED: React.CSSProperties = { fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }

export function ToolsSection({
  status,
  connections,
  onManage
}: ToolsSectionProps): React.JSX.Element {
  const catalog = useIntegrationCatalog()
  const live = connections.filter((c) => c.status !== 'revoked')
  const entry = (provider: string): { name: string; mark: string } => {
    const hit = catalog.find((i) => i.id === provider)
    return hit ?? { name: capitalize(provider), mark: provider.slice(0, 2).toUpperCase() }
  }
  return (
    <Section
      id="tools"
      title="Connected tools"
      sub="Tool accounts Solus can read from. Which documents flow into a project is chosen in that project."
      action={
        live.length > 0 ? (
          <Button kind="ghost" size="sm" onClick={onManage}>
            Manage connected accounts →
          </Button>
        ) : undefined
      }
    >
      {status === 'loading' && <div style={MUTED}>Loading connected accounts…</div>}
      {status === 'ready' && live.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ ...MUTED, flex: 1, minWidth: 240 }}>
            No tool accounts are connected yet. Link GitHub, Onshape, KiCad and more once, then use
            them in any project.
          </div>
          <Button kind="soft" size="sm" onClick={onManage}>
            Connect a tool
          </Button>
        </div>
      )}
      {live.map((c, i) => (
        <div key={c.id} className="settings-row-in" style={settingsStagger(i)}>
          <ToolRow connection={c} {...entry(c.provider)} />
        </div>
      ))}
    </Section>
  )
}
