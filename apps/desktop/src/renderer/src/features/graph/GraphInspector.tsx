// Right-hand inspector rail of the Context Model screen. Node inspection
// (properties, sources, cross-domain links) activates with the live graph
// view; SOLUSDEV-152 removed the prototype node data, so until entities
// render the rail honestly explains what will appear here.
import { Icons } from '../../components/ui/icons.constants'

export function GraphInspector(): React.JSX.Element {
  return (
    <div
      style={{
        width: 318,
        borderLeft: '1px solid var(--bd)',
        background: 'var(--sur)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        overflowY: 'auto'
      }}
    >
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          padding: 32,
          textAlign: 'center'
        }}
      >
        <span style={{ color: 'var(--mut)', opacity: 0.6 }}>
          <Icons.search size={26} />
        </span>
        <div style={{ fontSize: 13, color: 'var(--mut)', lineHeight: 1.6 }}>
          Once your graph has entities, selecting a node here shows its properties, sources, and
          links across domains.
        </div>
      </div>
    </div>
  )
}
