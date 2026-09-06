// SOLUSDEV-235 — one extension in detail: header (identity, meta, install
// actions) over three tabs. Installing goes through the permissions step;
// uninstalling is a confirmed action: it removes the extension's views from
// the project, so it is never one click.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { relativeTime } from '../../lib/relativeTime'
import { ModalShell } from '../workspace/modals'
import { ExtensionIconTile, PublisherBadge } from './ExtensionCard'
import { installsLabel, isFirstParty } from './extensionLogic'
import { PinButton } from './detail/PinButton'
import type { ExtensionView } from './extension.types'
import type { ExtensionActions } from './extensionActions'
import { GrantPermissionsModal } from './detail/GrantPermissionsModal'
import { HeaderActions } from './detail/HeaderActions'
import { OverviewTab } from './detail/OverviewTab'
import { PermissionsTab } from './detail/PermissionsTab'
import { SettingsTab } from './detail/SettingsTab'
import {
  useInstallFlow,
  type GrantStep as GrantStepState,
  type InstallFlow,
  type Notice
} from './detail/useInstallFlow'

export type DetailTab = 'overview' | 'settings' | 'permissions'

const TABS: ReadonlyArray<{ id: DetailTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'settings', label: 'Settings' },
  { id: 'permissions', label: 'Permissions' }
]

/** "Solus · v1.2.0 → 1.3.0 available · 412 installs · updated 2d ago". */
function metaLine(view: ExtensionView): string {
  const { catalog, state } = view
  const version = state.pinnedVersion ?? catalog.latestVersion
  const update = state.updateAvailable
  return [
    catalog.publisher,
    update ? `v${version} → ${update.version} available` : `v${version}`,
    installsLabel(catalog.installCount),
    `updated ${relativeTime(catalog.updatedAt)}`,
    ...(catalog.inCatalog ? [] : ['no longer in the catalog'])
  ].join(' · ')
}

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
  const flow = useInstallFlow(view, actions)
  const { catalog } = view

  const confirmUninstall = async (): Promise<void> => {
    const removed = await flow.uninstall()
    setConfirmingUninstall(false)
    if (removed) onBack()
  }

  return (
    <div>
      <BackLink onBack={onBack} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 14 }}>
        <ExtensionIconTile size={56} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              {catalog.name}
            </h1>
            <PublisherBadge publisher={catalog.publisher} verified={catalog.verified} />
            {isFirstParty(view.manifest) && <FirstPartyBadge />}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>{metaLine(view)}</div>
        </div>
        <PinButton slug={catalog.slug} />
        <HeaderActions
          view={view}
          actions={actions}
          flow={flow}
          onUninstall={() => setConfirmingUninstall(true)}
        />
      </div>
      {flow.notice && <FlowNotice notice={flow.notice} />}

      <Tabs tab={tab} onChange={setTab} />
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

      {flow.step && <GrantStep view={view} flow={flow} />}
      {confirmingUninstall && (
        <UninstallModal
          name={catalog.name}
          onClose={() => setConfirmingUninstall(false)}
          onConfirm={() => void confirmUninstall()}
        />
      )}
    </div>
  )
}

/** A first-party bundle: its backend, graph kinds and SOL tools are Solus code
 *  (ADR-035 as amended for STORE ST1), not community code in a sandbox. */
function FirstPartyBadge(): React.JSX.Element {
  return (
    <span
      data-testid="first-party-badge"
      title="Its backend, graph kinds and SOL tools are implemented inside Solus"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 7px',
        borderRadius: 3,
        border: '1px solid color-mix(in srgb, var(--acc) 45%, var(--bd))',
        background: 'color-mix(in srgb, var(--acc) 9%, var(--sur2))'
      }}
    >
      <Mono size={8.5} ls="0.12em" color="var(--acc)">
        FIRST-PARTY
      </Mono>
    </span>
  )
}

function FlowNotice({ notice }: { notice: Notice }): React.JSX.Element {
  return (
    <div
      role="status"
      style={{
        fontSize: 12,
        marginTop: 10,
        color: notice.kind === 'error' ? 'var(--warn)' : 'var(--mut)'
      }}
    >
      {notice.text}
    </div>
  )
}

/** The permissions step, fed from the flow's open step. */
function GrantStep({ view, flow }: { view: ExtensionView; flow: InstallFlow }): React.JSX.Element {
  const { catalog, state } = view
  const step = flow.step as GrantStepState
  return (
    <GrantPermissionsModal
      name={catalog.name}
      version={state.updateAvailable?.version ?? catalog.latestVersion}
      publisher={catalog.publisher}
      verified={catalog.verified}
      mode={step.mode}
      scopes={step.scopes}
      network={step.network}
      privacyPolicyUrl={catalog.assetUrls.privacyPolicy}
      busy={flow.busy}
      error={flow.stepError}
      onGrant={() => void flow.grant()}
      onCancel={flow.cancel}
    />
  )
}

function BackLink({ onBack }: { onBack: () => void }): React.JSX.Element {
  return (
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
  )
}

function Tabs({
  tab,
  onChange
}: {
  tab: DetailTab
  onChange: (tab: DetailTab) => void
}): React.JSX.Element {
  return (
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
            onClick={() => onChange(t.id)}
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
        Its widgets, tools and the graph data it added leave this project. Its settings are removed
        too.
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
