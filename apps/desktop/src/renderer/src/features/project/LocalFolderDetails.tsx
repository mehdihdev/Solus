// What the LOCAL FOLDER card shows beneath the path once the folder is a graph
// source (SOLUSDEV-249 / I2): the scan state, and one row per project the
// scan recognised — tool mark, name, folder-relative path, and its Open-in
// buttons. Everything here is read off the API's view; nothing is guessed.
import { Mono } from '../../components/ui/Mono'
import type { Source } from '../../lib/api/resources'
import type {
  DetectedProject,
  LocalOpenTool,
  OpenLocalFolderResult
} from '../../lib/api/resources.localfolder'
import './localFolder.css'
import { NOTHING_DETECTED_TEXT, ROW_STAGGER_MS, scanState, toolMark } from './localFolder.constants'
import { OpenInButtons } from './OpenInButtons'

const ONE_LINE: React.CSSProperties = {
  display: 'block',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}

/** "Scanning…" (breathing) · "Scanned 12 min ago" · the error, verbatim. */
export function ScanStateLine({ source }: { source: Source | null }): React.JSX.Element | null {
  const state = scanState(source)
  if (!state) return null
  const color = state.kind === 'error' ? 'var(--err)' : 'var(--mut)'
  return (
    <div
      data-testid="scan-state"
      className={state.kind === 'scanning' ? 'local-scan-shimmer' : undefined}
      style={{ fontSize: 10.5, color, lineHeight: 1.5 }}
    >
      {state.text}
    </div>
  )
}

/** The two-letter square a detected row leads with, tinted by its domain. */
function ToolMark({ tool }: { tool: string }): React.JSX.Element {
  const { mark, color } = toolMark(tool)
  return (
    <span
      aria-hidden
      style={{
        width: 24,
        height: 24,
        borderRadius: 5,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        color,
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0
      }}
    >
      {mark}
    </span>
  )
}

function DetectedRow({
  project,
  index,
  disabledReason,
  onOpen
}: {
  project: DetectedProject
  index: number
  disabledReason: string | null
  onOpen: (tool: LocalOpenTool) => Promise<OpenLocalFolderResult | null>
}): React.JSX.Element {
  return (
    <li
      className="local-row-in"
      data-testid="detected-row"
      style={{
        // Wraps: in Home's 420px column the button group drops onto its own
        // line under the name/path instead of widening the card (live-run fix).
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px 10px',
        alignItems: 'center',
        padding: '8px 0',
        borderTop: '1px solid var(--bd)',
        minWidth: 0,
        animationDelay: `${index * ROW_STAGGER_MS}ms`
      }}
    >
      <ToolMark tool={project.tool} />
      <div data-testid="detected-name" style={{ flex: '1 1 140px', minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 500, ...ONE_LINE }} title={project.name}>
          {project.name}
        </div>
        <div title={project.path} style={ONE_LINE}>
          <Mono size={10} style={{ textTransform: 'none' }}>
            {project.path}
          </Mono>
        </div>
      </div>
      <div data-testid="detected-open" style={{ flex: '0 1 auto', minWidth: 0 }}>
        <OpenInButtons
          targets={project.open_targets}
          disabledReason={disabledReason}
          onOpen={onOpen}
        />
      </div>
    </li>
  )
}

export interface DetectedProjectListProps {
  projects: readonly DetectedProject[]
  /** True once a scan has finished, so an empty list can be called empty. */
  scanned: boolean
  disabledReason: string | null
  onOpen: (entityId: string, tool: LocalOpenTool) => Promise<OpenLocalFolderResult | null>
}

export function DetectedProjectList({
  projects,
  scanned,
  disabledReason,
  onOpen
}: DetectedProjectListProps): React.JSX.Element | null {
  if (projects.length === 0) {
    if (!scanned) return null
    return (
      <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
        {NOTHING_DETECTED_TEXT}
      </div>
    )
  }
  return (
    <ul
      aria-label="Detected projects"
      style={{ listStyle: 'none', margin: 0, padding: 0, minWidth: 0, width: '100%' }}
    >
      {projects.map((project, index) => (
        <DetectedRow
          key={project.entity_id}
          project={project}
          index={index}
          disabledReason={disabledReason}
          onOpen={(tool) => onOpen(project.entity_id, tool)}
        />
      ))}
    </ul>
  )
}
