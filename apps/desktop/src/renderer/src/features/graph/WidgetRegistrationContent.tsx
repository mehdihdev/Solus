import type { Entity } from '../../lib/api/resources'
import type { SolMode } from '../../store/settingsStore'
import { isWidgetRegistration } from './widgetRegistrationProjection'

interface Props {
  entity: Entity
  projectId: string
  mode: SolMode
  onOpenBench?: () => void
  onOpenWidget?: (slug: string) => void
}

function unavailable(entity: Entity, mode: SolMode): string | null {
  const metadata = entity.properties ?? {}
  if (metadata.blocked === true)
    return mode === 'Guide'
      ? 'Your team has blocked this widget. It cannot be opened.'
      : 'Blocked by team'
  if (metadata.enabled !== true)
    return mode === 'Guide'
      ? 'This widget is disabled. Enable it in the Store to open it.'
      : 'Disabled'
  if (!Array.isArray(metadata.views) || !metadata.views.includes('page'))
    return mode === 'Guide'
      ? 'This widget has no page view. Its available views are managed in Live Bench or the Store.'
      : 'No page view'
  return null
}

export function WidgetRegistrationContent({
  entity,
  projectId,
  mode,
  onOpenBench,
  onOpenWidget
}: Props): React.JSX.Element | null {
  if (!isWidgetRegistration(entity, projectId)) return null
  if (entity.type === 'solus:live_bench')
    return (
      <div className="graph-node-content">
        <p>
          {mode === 'Guide'
            ? 'View your connected robots and their live signals.'
            : 'Robot telemetry'}
        </p>
        {onOpenBench && (
          <button type="button" onClick={onOpenBench}>
            Open Live Bench
          </button>
        )}
      </div>
    )
  return <InstalledWidget entity={entity} mode={mode} onOpenWidget={onOpenWidget} />
}

function InstalledWidget({
  entity,
  mode,
  onOpenWidget
}: Pick<Props, 'entity' | 'mode' | 'onOpenWidget'>): React.JSX.Element {
  const metadata = entity.properties ?? {}
  const reason = unavailable(entity, mode)
  const slug = typeof metadata.slug === 'string' ? metadata.slug : null
  return (
    <div className="graph-node-content">
      <p>
        {typeof metadata.version === 'string' ? `Version ${metadata.version}` : 'Version unknown'}
        {typeof metadata.publisher === 'string' ? ` · ${metadata.publisher}` : ''}
      </p>
      <p>{reason ?? 'Installed'}</p>
      {!reason && slug && onOpenWidget && (
        <button type="button" onClick={() => onOpenWidget(slug)}>
          Open {entity.name}
        </button>
      )}
    </div>
  )
}
