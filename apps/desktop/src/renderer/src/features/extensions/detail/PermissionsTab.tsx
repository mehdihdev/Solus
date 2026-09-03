// SOLUSDEV-235 — detail › Permissions: every scope the extension holds or has
// not asked for, plus the standing guarantee that no extension writes to
// hardware directly (CLAUDE.md §7: destructive effects go through the
// confirmation gate — CTR-03).
import { Card } from '../../../components/ui/Card'
import { Icons, type IconName } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import { PERMISSION_TEXT } from '../extensionLogic'
import type { ExtensionView, PermissionScope } from '../extension.types'

const SCOPE_ICON: Readonly<Record<PermissionScope, IconName>> = {
  'graph.read': 'hex',
  'telemetry.read': 'wave',
  'sources.read': 'link',
  'findings.write': 'triangle'
}

export function PermissionsTab({ view }: { view: ExtensionView }): React.JSX.Element {
  const { permissions } = view.manifest
  return (
    <div style={{ maxWidth: 640, paddingTop: 12 }}>
      {permissions.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--mut)', padding: '10px 0' }}>
          This extension asks for no permissions.
        </div>
      )}
      {permissions.map((p) => {
        const Icon = Icons[SCOPE_ICON[p.scope]]
        const text = PERMISSION_TEXT[p.scope]
        const granted = p.status === 'granted'
        return (
          <div
            key={p.scope}
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
              <div style={{ fontSize: 13, fontWeight: 600 }}>{text.title}</div>
              <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2 }}>
                {granted ? text.detail : 'Not yet requested'}
              </div>
            </div>
            <Mono size={9.5} color={granted ? 'var(--ok)' : 'var(--mut)'}>
              {granted ? 'GRANTED' : 'NOT ASKED'}
            </Mono>
          </div>
        )
      })}
      <Card
        pad={14}
        style={{
          marginTop: 18,
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
