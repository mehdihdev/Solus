// Local tools reachable through the companion bridge (SOLUSDEV-72). Each row
// merges the registry entry with the live bridge status; the copy comes from
// toolStatusText (honest by construction) and the backend's connect_notice —
// this component invents nothing.
import { Mono } from '../../../components/ui/Mono'
import type { BridgeStatus, LocalTool } from '../../../lib/api/resources'
import { toolStatusText } from './presentation'

export interface LocalToolRowsProps {
  /** Null means UNKNOWN (API unreachable), not "no tools". */
  tools: LocalTool[] | null
  bridge: BridgeStatus | null
}

export function LocalToolRows({ tools, bridge }: LocalToolRowsProps): React.JSX.Element {
  if (tools === null) {
    return (
      <div style={{ fontSize: 12, color: 'var(--mut)' }}>
        Can&apos;t list local tools right now — the Solus API is unreachable.
      </div>
    )
  }
  if (tools.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--mut)' }}>No local tools are registered.</div>
  }
  return (
    <>
      {tools.map((tool) => (
        <div key={tool.type} style={{ padding: '12px 0', borderBottom: '1px solid var(--bd)' }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600 }}>
              {tool.display_name}
            </div>
            <Mono size={8.5} color="var(--mut)">
              {tool.url_host}
            </Mono>
            <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>
              {toolStatusText(tool, bridge)}
            </span>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 4 }}>
            {tool.connect_notice}
          </div>
        </div>
      ))}
    </>
  )
}
