// SOLUSDEV-235 — detail › Permissions: every scope and network origin the
// manifest declares, marked GRANTED / NOT GRANTED from the install row's real
// grant record, plus the standing guarantee that no extension writes to
// hardware directly (CLAUDE.md §7: destructive effects go through the
// confirmation gate — CTR-03).
import { Card } from '../../../components/ui/Card'
import { Icons, type IconName } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import { PERMISSION_TEXT } from '../extensionLogic'
import type { ExtensionView } from '../extension.types'
import { SCOPE_ICON } from './scopeIcons'

export function PermissionsTab({ view }: { view: ExtensionView }): React.JSX.Element {
  const { manifest, state } = view
  if (!manifest) {
    return (
      <div style={{ fontSize: 12.5, color: 'var(--mut)', padding: '22px 0' }}>
        Loading the extension’s manifest…
      </div>
    )
  }
  const { scopes, network } = manifest.permissions
  const statusOf = (granted: boolean): GrantStatus =>
    !state.installed ? 'absent' : granted ? 'granted' : 'missing'
  return (
    <div style={{ maxWidth: 640, paddingTop: 12 }}>
      {scopes.length + network.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--mut)', padding: '10px 0' }}>
          This extension asks for no permissions.
        </div>
      )}
      {scopes.map((scope) => (
        <GrantRow
          key={scope}
          icon={SCOPE_ICON[scope]}
          title={PERMISSION_TEXT[scope].title}
          detail={PERMISSION_TEXT[scope].detail}
          status={statusOf(state.grantedScopes.includes(scope))}
        />
      ))}
      {network.length > 0 && (
        <div style={{ margin: '18px 0 4px' }}>
          <Mono size={9.5} ls="0.18em">
            MAY CONNECT TO
          </Mono>
        </div>
      )}
      {network.map((origin) => (
        <GrantRow
          key={origin}
          icon="external"
          title={origin}
          detail="Requests go through Solus’ proxy, never from your machine directly."
          status={statusOf(state.grantedNetwork.includes(origin))}
        />
      ))}
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 12, lineHeight: 1.5 }}>
        Grants are per project. Solus enforces these scopes at every call; revoke by uninstalling.
      </div>
      <Card
        pad={14}
        style={{
          marginTop: 14,
          borderColor: 'color-mix(in srgb, var(--warn) 45%, var(--bd))',
          background: 'color-mix(in srgb, var(--warn) 8%, var(--sur))'
        }}
      >
        <div style={{ fontSize: 12.5, lineHeight: 1.55 }}>
          Extensions never write to hardware directly — anything that would move a motor goes
          through the approval queue, per your team instructions.
        </div>
      </Card>
    </div>
  )
}

/** `absent` is "not installed here"; `missing` is an install that lacks the grant (wireflow §5). */
type GrantStatus = 'granted' | 'missing' | 'absent'

const STATUS_COLOR: Readonly<Record<GrantStatus, string>> = {
  granted: 'var(--ok)',
  missing: 'var(--warn)',
  absent: 'var(--mut)'
}

function GrantRow({
  icon,
  title,
  detail,
  status
}: {
  icon: IconName
  title: string
  detail: string
  status: GrantStatus
}): React.JSX.Element {
  const Icon = Icons[icon]
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
      <span
        aria-hidden
        style={{
          width: 30,
          height: 30,
          borderRadius: 4,
          border: '1px solid var(--bd)',
          background: 'var(--sur2)',
          color: 'var(--mut)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0
        }}
      >
        <Icon size={13} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2 }}>{detail}</div>
      </div>
      <Mono size={9.5} color={STATUS_COLOR[status]}>
        {status === 'granted' ? 'GRANTED' : 'NOT GRANTED'}
      </Mono>
    </div>
  )
}
