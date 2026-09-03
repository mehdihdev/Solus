// SOLUSDEV-235 — the Store card (grid tile or list row) and the small badges
// shared with the detail header: icon tile, publisher badge, availability pill.
import type { KeyboardEvent } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons, type IconName } from '../../components/ui/icons.constants'
import type { ExtensionView, Publisher } from './extension.types'
import { PUBLISHER_LABEL, requirementLabel } from './extensionLogic'

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

export function ExtensionIconTile({
  icon,
  size = 36
}: {
  icon: IconName
  size?: number
}): React.JSX.Element {
  const Icon = Icons[icon]
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
      <Icon size={Math.round(size * 0.42)} />
    </div>
  )
}

export function PublisherBadge({ publisher }: { publisher: Publisher }): React.JSX.Element {
  const verified = publisher === 'solus'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 6px',
        borderRadius: 3,
        border: '1px solid var(--bd)',
        background: 'var(--sur2)',
        lineHeight: 1
      }}
    >
      <Mono size={8.5} ls="0.12em" color={verified ? 'var(--ok)' : 'var(--mut)'}>
        {PUBLISHER_LABEL[publisher]}
      </Mono>
      {verified && (
        <span style={{ color: 'var(--ok)', display: 'inline-flex' }}>
          <Icons.check size={9} title="Verified by Solus" />
        </span>
      )}
    </span>
  )
}

export function AvailabilityPill({ view }: { view: ExtensionView }): React.JSX.Element {
  if (view.availability === 'installed') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--ok)' }} />
        <Mono size={9.5} color="var(--ok)">
          INSTALLED
        </Mono>
      </span>
    )
  }
  const text =
    view.availability === 'needs_source' ? `NEEDS ${requirementLabel(view.missing)}` : 'AVAILABLE'
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
  onOpen: (extensionId: string) => void
}): React.JSX.Element {
  const { manifest } = view
  const open = (): void => onOpen(manifest.id)
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
      aria-label={`Open ${manifest.name}`}
      onClick={open}
      onKeyDown={onKeyDown}
      pad={compact ? 12 : 18}
      style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}
    >
      <ExtensionIconTile icon={manifest.icon} size={compact ? 32 : 36} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: compact ? 13 : 14, fontWeight: 600 }}>{manifest.name}</span>
          <PublisherBadge publisher={manifest.publisher} />
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
          {manifest.summary}
        </div>
      </div>
      <div style={{ flexShrink: 0, alignSelf: 'center', paddingLeft: 8 }}>
        <AvailabilityPill view={view} />
      </div>
    </Card>
  )
}
