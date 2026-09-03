// SOLUSDEV-235 / EXT-13 — the identity row shared by the page screen and the
// window root (wireflow §2 header, §3 chrome): icon tile · name · DEV badge ·
// publisher · version, and the optional "Open in window ↗". Every string from
// the manifest or the registry is rendered as text.
import type { ReactNode } from 'react'
import { Icons } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import { ExtensionIcon } from '../host/ExtensionIcon'

export function DevBadge(): React.JSX.Element {
  return (
    <span
      data-testid="dev-badge"
      title="Developer registration — loaded from a folder on this computer"
      style={{
        padding: '1px 5px',
        borderRadius: 3,
        border: '1px solid color-mix(in srgb, var(--warn) 55%, var(--bd))',
        background: 'color-mix(in srgb, var(--warn) 12%, var(--sur2))',
        lineHeight: 1.4
      }}
    >
      <Mono size={8.5} ls="0.14em" color="var(--warn)">
        DEV
      </Mono>
    </span>
  )
}

export function PageIconTile({
  svg,
  size = 24
}: {
  svg: string | null
  size?: number
}): React.JSX.Element {
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: 4,
        border: '1px solid var(--bd)',
        background: 'var(--sur2)',
        color: 'var(--mut)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
    >
      {svg ? (
        <ExtensionIcon svg={svg} size={Math.round(size * 0.6)} />
      ) : (
        <Icons.box size={Math.round(size * 0.5)} />
      )}
    </div>
  )
}

export interface PageHeaderProps {
  readonly name: string
  readonly iconSvg: string | null
  readonly isDev: boolean
  /** semver or `dev`; null while unknown. */
  readonly version: string | null
  readonly publisher: { readonly displayName: string; readonly verified: boolean } | null
  readonly onBack?: () => void
  readonly actions?: ReactNode
}

function metaLine(props: PageHeaderProps): string {
  const parts: string[] = []
  if (props.publisher) parts.push(`by ${props.publisher.displayName}`)
  if (props.version) parts.push(props.version === 'dev' ? 'dev' : `v${props.version}`)
  return parts.join(' · ')
}

export function PageHeader(props: PageHeaderProps): React.JSX.Element {
  const { name, iconSvg, isDev, publisher, onBack, actions } = props
  return (
    <div
      data-testid="ext-page-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '12px 18px',
        borderBottom: '1px solid var(--bd)',
        background: 'var(--sur)',
        flexShrink: 0
      }}
    >
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          aria-label="Back"
          className="interactive"
          style={{
            background: 'transparent',
            border: 'none',
            padding: 4,
            borderRadius: 3,
            color: 'var(--mut)',
            display: 'inline-flex',
            cursor: 'pointer'
          }}
        >
          <Icons.arrowL size={13} />
        </button>
      )}
      <PageIconTile svg={iconSvg} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <h1
            style={{
              margin: 0,
              fontSize: 14.5,
              fontWeight: 600,
              letterSpacing: '-0.01em',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}
          >
            {name}
          </h1>
          {isDev && <DevBadge />}
          {publisher?.verified && (
            <span style={{ color: 'var(--ok)', display: 'inline-flex' }}>
              <Icons.verified size={12} title="Verified by Solus" />
            </span>
          )}
        </div>
        <Mono size={9.5} style={{ textTransform: 'none' }}>
          {metaLine(props)}
        </Mono>
      </div>
      {actions}
    </div>
  )
}
