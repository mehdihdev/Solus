// SOLUSDEV-235 — the Store card (grid tile or list row) and the small badges
// shared with the detail header: icon tile, publisher badge, availability pill.
import type { KeyboardEvent } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import type { ExtensionView } from './extension.types'
import { requirementLabel } from './extensionLogic'

export type StoreLayout = 'grid' | 'list'

/** Mono section heading — "INSTALLED", "WHAT IT ADDS", … */
export function SectionLabel({ children }: { children: string }): React.JSX.Element {
  return (
    <div style={{ margin: '22px 0 10px' }}>
      <Mono size={9.5} ls="0.18em">
        {children}
      </Mono>
    </div>
  )
}

/** The icon tile. Bundle icons are served behind the API's bearer auth, so
 *  the tile renders the shared glyph rather than an `<img>` that cannot load. */
export function ExtensionIconTile({ size = 36 }: { size?: number }): React.JSX.Element {
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
      <Icons.box size={Math.round(size * 0.42)} />
    </div>
  )
}

/** `<PUBLISHER> ✓` in the ok color for a verified publisher, `COMMUNITY` muted otherwise. */
export function PublisherBadge({
  publisher,
  verified
}: {
  publisher: string
  verified: boolean
}): React.JSX.Element {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 6px 2px 7px',
        borderRadius: 4,
        border: verified
          ? '1px solid color-mix(in srgb, var(--ok) 45%, var(--bd))'
          : '1px solid var(--bd)',
        background: verified ? 'color-mix(in srgb, var(--ok) 9%, var(--sur2))' : 'var(--sur2)',
        lineHeight: 1
      }}
    >
      <Mono size={8.5} ls="0.12em" color={verified ? 'var(--ok)' : 'var(--mut)'}>
        {verified ? publisher : 'COMMUNITY'}
      </Mono>
      {verified && (
        <span style={{ color: 'var(--ok)', display: 'inline-flex' }}>
          <Icons.verified size={11} title="Verified by Solus" />
        </span>
      )}
    </span>
  )
}

const PILL_TEXT: Readonly<Record<'blocked' | 'available', string>> = {
  blocked: 'BLOCKED',
  available: 'AVAILABLE'
}

export function AvailabilityPill({ view }: { view: ExtensionView }): React.JSX.Element {
  if (view.availability === 'installed') {
    const update = view.state.updateAvailable
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--ok)' }} />
        <Mono size={9.5} color="var(--ok)">
          INSTALLED
        </Mono>
        {update && (
          <span
            title={`Update available: ${update.version}`}
            style={{ color: 'var(--acc)', fontSize: 11, lineHeight: 1 }}
          >
            ↑
          </span>
        )}
      </span>
    )
  }
  const text =
    view.availability === 'needs_source'
      ? `NEEDS ${requirementLabel(view.missing)}`
      : PILL_TEXT[view.availability]
  return (
    <Mono size={9.5} color="var(--mut)" style={{ opacity: 0.8 }}>
      {text}
    </Mono>
  )
}

export function ExtensionCard({
  view,
  layout,
  onOpen
}: {
  view: ExtensionView
  layout: StoreLayout
  onOpen: (slug: string) => void
}): React.JSX.Element {
  const { catalog } = view
  const open = (): void => onOpen(catalog.slug)
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      open()
    }
  }
  const compact = layout === 'list'
  return (
    <Card
      role="button"
      tabIndex={0}
      aria-label={`Open ${catalog.name}`}
      onClick={open}
      onKeyDown={onKeyDown}
      pad={compact ? 12 : 18}
      style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}
    >
      <ExtensionIconTile size={compact ? 32 : 36} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: compact ? 13 : 14, fontWeight: 600 }}>{catalog.name}</span>
          <PublisherBadge publisher={catalog.publisher} verified={catalog.verified} />
        </div>
        <div
          style={{
            fontSize: 12,
            color: 'var(--mut)',
            marginTop: 4,
            lineHeight: 1.5,
            ...(compact
              ? { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }
              : {})
          }}
        >
          {catalog.summary}
        </div>
      </div>
      <div style={{ flexShrink: 0, alignSelf: 'center', paddingLeft: 8 }}>
        <AvailabilityPill view={view} />
      </div>
    </Card>
  )
}
