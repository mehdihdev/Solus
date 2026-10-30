// The node side panel's shared chrome (design template, Workspace side panel): a header
// row with the node's domain dot, a mono label (`SOURCE · ONSHAPE`, `KICAD · PCB`),
// the close ✕, the title, and only the facts we actually have; a footer grid for the
// panel's actions. Pure presentation — owners decide what goes in.
import type { ReactNode } from 'react'
import { Mono } from '../../../components/ui/Mono'
import type { Entity } from '../../../lib/api/resources'

export interface NodePanelMeta {
  /** Who wrote it — only when known (e.g. `SOL` for a SOL-authored note). */
  authoredBy?: string
  /** `relativeTime(updated_at)` — only when the record carries a timestamp. */
  editedAgo?: string
}

function typeWords(entity: Entity): string {
  return entity.type === 'solus_config' ? 'root + project' : entity.type.replaceAll('_', ' ')
}

/** `SOURCE · GITHUB` for an account anchor; else `<source type or domain> · <type>`. */
export function panelLabel(entity: Entity, sourceType: string | null): string {
  if (entity.type === 'integration_account') {
    const provider = entity.properties?.provider
    const name = typeof provider === 'string' && provider ? provider : entity.name
    return `SOURCE · ${name}`.toUpperCase()
  }
  return `${sourceType ?? entity.domain} · ${typeWords(entity)}`.toUpperCase()
}

export function NodePanelHeader({
  entity,
  label,
  title,
  meta,
  onClose
}: {
  entity: Entity
  label: string
  /** Omitted when the owned body renders its own heading. */
  title?: string
  meta?: NodePanelMeta
  onClose?: () => void
}): React.JSX.Element {
  const rows = [
    meta?.authoredBy ? (['AUTHORED BY', meta.authoredBy] as const) : null,
    meta?.editedAgo ? (['LAST EDITED', meta.editedAgo] as const) : null
  ].filter((row): row is readonly ['AUTHORED BY' | 'LAST EDITED', string] => row !== null)
  return (
    <header className="node-panel-header" data-domain={entity.domain}>
      <div className="node-panel-header-row">
        <i className="graph-domain-dot" aria-hidden="true" />
        <Mono size={10} ls="0.08em" className="node-panel-label">
          {label}
        </Mono>
        {onClose && (
          <button
            type="button"
            className="node-panel-close"
            aria-label="Close panel"
            onClick={onClose}
          >
            ✕
          </button>
        )}
      </div>
      {title && <h2>{title}</h2>}
      {rows.length > 0 && (
        <dl className="node-panel-meta">
          {rows.map(([key, value]) => (
            <div key={key}>
              <dt>
                <Mono size={10}>{key}</Mono>
              </dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </header>
  )
}

/** The panel's action strip; one column per child. */
export function NodePanelFooter({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="node-panel-footer">{children}</div>
}
