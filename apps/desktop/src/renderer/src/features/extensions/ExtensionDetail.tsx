// SOLUSDEV-235 — one extension in detail: header (identity, meta, install
// actions) over three tabs. Uninstall is a confirmed action: it removes the
// extension's widgets and checks from the project, so it is never one click.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { relativeTime } from '../../lib/relativeTime'
import { ModalShell } from '../workspace/modals'
import { ExtensionIconTile, PublisherBadge } from './ExtensionCard'
import { installsLabel, requirementLabel } from './extensionLogic'
import type { ExtensionView } from './extension.types'
import type { ExtensionActions } from './useExtensions'
import { OverviewTab } from './detail/OverviewTab'
import { SettingsTab } from './detail/SettingsTab'
import { PermissionsTab } from './detail/PermissionsTab'

export type DetailTab = 'overview' | 'settings' | 'permissions'

const TABS: ReadonlyArray<{ id: DetailTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'settings', label: 'Settings' },
  { id: 'permissions', label: 'Permissions' }
]

const PUBLISHER_NAME = { solus: 'Solus', community: 'Community' } as const

export function ExtensionDetail({
  view,
  actions,
  onBack
}: {
  view: ExtensionView
  actions: ExtensionActions
  onBack: () => void
}): React.JSX.Element {
  const [tab, setTab] = useState<DetailTab>('overview')
  const [confirmingUninstall, setConfirmingUninstall] = useState(false)
  const { manifest } = view
  const meta = [
    PUBLISHER_NAME[manifest.publisher],
    `v${manifest.version}`,
    installsLabel(manifest.installs),
    `updated ${relativeTime(manifest.updatedAt)}`
  ].join(' · ')

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        aria-label="Back to Store"
        className="interactive"
        style={{
          background: 'transparent',
          border: 'none',
          padding: '2px 4px',
          marginLeft: -4,
          borderRadius: 3,
          color: 'var(--acc)',
          fontFamily: 'var(--font-ui)',
          fontSize: 12.5,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          cursor: 'pointer'
        }}
      >
        <Icons.arrowL size={12} /> Store
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 14 }}>
        <ExtensionIconTile icon={manifest.icon} size={56} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              {manifest.name}
            </h1>
            <PublisherBadge publisher={manifest.publisher} />
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>{meta}</div>
        </div>
        <HeaderActions
          view={view}
          actions={actions}
          onUninstall={() => setConfirmingUninstall(true)}
        />
      </div>

      <div
        role="tablist"
        aria-label="Extension sections"
        style={{ display: 'flex', gap: 4, marginTop: 24, borderBottom: '1px solid var(--bd)' }}
      >
        {TABS.map((t) => {
          const active = tab === t.id
          return (
            <button
              key={t.id}
              id={`extension-tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls="extension-tabpanel"
              onClick={() => setTab(t.id)}
              className="interactive"
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${active ? 'var(--acc)' : 'transparent'}`,
                marginBottom: -1,
                padding: '8px 14px',
                fontFamily: 'var(--font-ui)',
                fontSize: 13,
                fontWeight: active ? 600 : 500,
                color: active ? 'var(--tx)' : 'var(--mut)',
                cursor: 'pointer',
                borderRadius: '3px 3px 0 0'
              }}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <div
        role="tabpanel"
        id="extension-tabpanel"
        aria-labelledby={`extension-tab-${tab}`}
        style={{ marginTop: 6 }}
      >
        {tab === 'overview' && <OverviewTab view={view} />}
        {tab === 'settings' && <SettingsTab view={view} actions={actions} />}
        {tab === 'permissions' && <PermissionsTab view={view} />}
      </div>

      {confirmingUninstall && (
        <UninstallModal
          name={manifest.name}
          onClose={() => setConfirmingUninstall(false)}
          onConfirm={() => {
            actions.uninstall(manifest.id)
            setConfirmingUninstall(false)
            onBack()
          }}
        />
      )}
    </div>
  )
}

function HeaderActions({
  view,
  actions,
  onUninstall
}: {
  view: ExtensionView
  actions: ExtensionActions
  onUninstall: () => void
}): React.JSX.Element {
  const { manifest, state } = view
  if (state.installed) {
    return (
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        <Button
          kind="soft"
          size="sm"
          onClick={() => actions.setEnabled(manifest.id, !state.enabled)}
        >
          {state.enabled ? 'Disable' : 'Enable'}
        </Button>
        <Button kind="danger" size="sm" onClick={onUninstall}>
          Uninstall
        </Button>
      </div>
    )
  }
  const blocked = view.availability === 'needs_source'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexShrink: 0 }}>
      {blocked && (
        <Mono size={9.5} color="var(--mut)">
          NEEDS {requirementLabel(view.missing)}
        </Mono>
      )}
      <Button
        kind="primary"
        size="sm"
        disabled={blocked}
        title={blocked ? 'Connect a required source first' : undefined}
        onClick={() => actions.install(manifest.id)}
      >
        Install
      </Button>
    </div>
  )
}

function UninstallModal({
  name,
  onClose,
  onConfirm
}: {
  name: string
  onClose: () => void
  onConfirm: () => void
}): React.JSX.Element {
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Uninstall {name}?</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Its widgets and checks leave this project. Graph data it already added stays. Your settings
        are kept if you reinstall.
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" onClick={onConfirm}>
          Uninstall extension
        </Button>
      </div>
    </ModalShell>
  )
}
