// SOLUSDEV-235 — the permissions step that precedes an install or a widening
// update (extensions-runtime wireflow §1). Scopes and origins are rendered
// from Solus copy keyed by the closed scope set — never text from a manifest —
// and the grant is all-or-nothing: the button grants exactly the listed set.
import { useEffect } from 'react'
import type { PermissionScope } from '@solus/shared-types'
import { Button } from '../../../components/ui/Button'
import { Icons } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import { apiBaseUrl, joinUrl } from '../../../lib/api/client'
import { ModalShell } from '../../workspace/modals'
import { PublisherBadge } from '../ExtensionCard'
import { PERMISSION_TEXT } from '../extensionLogic'
import { SCOPE_ICON } from './scopeIcons'

export type GrantMode = 'install' | 'update'

export interface GrantPermissionsModalProps {
  name: string
  version: string
  publisher: string
  verified: boolean
  mode: GrantMode
  /** The scopes to grant — the whole declared set on install, only the additions on update. */
  scopes: readonly PermissionScope[]
  network: readonly string[]
  /** Relative API route of the bundle's `store.privacy_policy`, or null. */
  privacyPolicyUrl: string | null
  busy: boolean
  error: string | null
  onGrant: () => void
  onCancel: () => void
}

const VERB: Readonly<Record<GrantMode, { title: string; grant: string; busy: string }>> = {
  install: { title: 'Install', grant: 'Grant and install', busy: 'Installing…' },
  update: { title: 'Update', grant: 'Grant and update', busy: 'Updating…' }
}

export function GrantPermissionsModal(props: GrantPermissionsModalProps): React.JSX.Element {
  const { name, mode, scopes, network, busy, error, onGrant, onCancel } = props
  const asksForNothing = scopes.length === 0 && network.length === 0
  const verb = VERB[mode]
  const grantLabel = busy ? verb.busy : asksForNothing ? verb.title : verb.grant

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <ModalShell onClose={onCancel} width={520}>
      <div role="dialog" aria-modal="true" aria-label={`${verb.title} ${name}`}>
        <Header {...props} />
        <div style={{ marginTop: 16 }}>
          {asksForNothing ? (
            <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>
              {name} asks for nothing. It runs entirely inside its sandbox.
            </div>
          ) : (
            <Requests {...props} />
          )}
        </div>
        {error && (
          <div role="alert" style={{ fontSize: 12, color: 'var(--warn)', marginTop: 14 }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
          <Button kind="ghost" size="sm" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button kind="primary" size="sm" onClick={onGrant} disabled={busy}>
            {grantLabel}
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}

function Header({
  name,
  version,
  publisher,
  verified,
  mode,
  onCancel
}: GrantPermissionsModalProps): React.JSX.Element {
  return (
    <div style={{ borderBottom: '1px solid var(--bd)', paddingBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Mono size={11} ls="0.16em" color="var(--tx)" style={{ flex: 1 }}>
          {VERB[mode].title} {name}
        </Mono>
        <Mono size={9.5}>v{version}</Mono>
        <button
          type="button"
          aria-label="Close"
          onClick={onCancel}
          className="interactive"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--mut)',
            cursor: 'pointer',
            display: 'inline-flex',
            padding: 2
          }}
        >
          <Icons.x size={12} />
        </button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12 }}>
        <span style={{ color: 'var(--mut)' }}>by</span>
        <PublisherBadge publisher={publisher} verified={verified} />
      </div>
    </div>
  )
}

function Requests({
  name,
  version,
  mode,
  scopes,
  network,
  privacyPolicyUrl
}: GrantPermissionsModalProps): React.JSX.Element {
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        {mode === 'install' ? `${name} asks for` : `${version} additionally asks for`}
      </div>
      {scopes.map((scope) => (
        <ScopeRow key={scope} scope={scope} />
      ))}
      {network.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 600, marginTop: 14 }}>It may connect to</div>
          {network.map((origin) => (
            <div
              key={origin}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 0',
                fontSize: 12.5,
                fontFamily: 'var(--font-mono)'
              }}
            >
              <span style={{ color: 'var(--mut)', display: 'inline-flex' }}>
                <Icons.external size={11} />
              </span>
              {origin}
            </div>
          ))}
        </>
      )}
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 14, lineHeight: 1.55 }}>
        Nothing else. Solus performs every call on its behalf with your account; the extension never
        receives your credentials.
      </div>
      {privacyPolicyUrl && (
        <a
          href={joinUrl(apiBaseUrl, privacyPolicyUrl)}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            marginTop: 12,
            fontSize: 12.5,
            color: 'var(--acc)',
            textDecoration: 'none'
          }}
        >
          Privacy policy <Icons.external size={10} />
        </a>
      )}
    </>
  )
}

function ScopeRow({ scope }: { scope: PermissionScope }): React.JSX.Element {
  const Icon = Icons[SCOPE_ICON[scope]]
  const text = PERMISSION_TEXT[scope]
  return (
    <div
      data-testid="grant-scope"
      style={{ display: 'flex', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--bd)' }}
    >
      <span
        aria-hidden
        style={{
          width: 28,
          height: 28,
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
        <Icon size={12} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{text.title}</span>
          <Mono size={9.5} style={{ textTransform: 'none' }}>
            {scope}
          </Mono>
        </div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2, lineHeight: 1.5 }}>
          {text.detail}
        </div>
      </div>
    </div>
  )
}
