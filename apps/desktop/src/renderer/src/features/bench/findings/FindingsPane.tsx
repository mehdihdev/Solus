// SOLUSDEV-321 P2-T7 — the Live Bench Findings pane, under LIVE REASONING (widget-canvas.md
// 2026-09-15, local-connections.md "Findings pane"): one group per connected robot, its open
// findings by severity with count and last seen, the six actions on each card, the finding a
// signal marker opened, and what the rules could not check. It mounts the Bench's one project
// stream; findings arrive through the findings live key it bumps — never polled.
import { useEffect, useRef, useState } from 'react'
import type { BenchSession } from '../../../lib/api/resources'
import { relativeTime } from '../../../lib/relativeTime'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceEvents } from '../../graph/useWorkspaceEvents'
import { NOTHING_OUT_OF_RANGE } from '../DeviceBenchView'
import { FindingCard } from './FindingCard'
import {
  connectedRobots,
  loadMissingSignals,
  severityGroups,
  useRobotFindings,
  useSelectedFinding,
  type RobotFindings,
  type SeverityGroup
} from './useRobotFindings'

interface FindingsPaneProps {
  projectId: string
  sessions: readonly BenchSession[] | null
  /** The finding a signal marker opened: read by id and shown expanded until closed. */
  selectedFindingId?: string | null
  onCloseSelected?: () => void
}

export function FindingsPane({
  projectId,
  sessions,
  selectedFindingId = null,
  onCloseSelected
}: FindingsPaneProps): React.JSX.Element | null {
  const { groups, refetch } = useRobotFindings(projectId, connectedRobots(sessions))
  // ponytail: graph.changed also bumps the findings live key (250 ms coalesced); handing it the
  // refetch too re-reads at once, for one extra read per graph.changed frame.
  const liveError = useWorkspaceEvents(projectId, refetch)
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  if (!groups.length && !selectedFindingId) return null
  const open = groups.reduce((total, group) => total + group.findings.length, 0)
  return (
    <section aria-label="Findings">
      <div className="bench-section-heading bench-reasoning-heading">
        <span>FINDINGS · {open} OPEN</span>
      </div>
      {guide && (
        <p className="bench-device-chips">
          Solus checks each connected robot&apos;s live signals against its parts&apos; limits and
          raises a finding when one goes out of range. Open a finding for its evidence and likely
          causes; its actions ask SOL, open the code, or record what you did.
        </p>
      )}
      {liveError && <p role="status">{liveError}</p>}
      {selectedFindingId && (
        <OpenedFinding
          projectId={projectId}
          findingId={selectedFindingId}
          onClose={onCloseSelected}
          onChanged={refetch}
        />
      )}
      {groups.map((group) => (
        <RobotGroup key={group.robotId} projectId={projectId} group={group} onChanged={refetch} />
      ))}
    </section>
  )
}

function RobotGroup({
  projectId,
  group,
  onChanged
}: {
  projectId: string
  group: RobotFindings
  onChanged: () => void
}): React.JSX.Element {
  return (
    <section aria-label={`Findings for ${group.label}`}>
      <h3>
        {group.label} · {group.findings.length} open
      </h3>
      {group.status === 'loading' && <p role="status">Loading findings…</p>}
      {group.status === 'failed' && (
        <p role="alert">Findings are unavailable for {group.label}; what it shows is unknown.</p>
      )}
      {group.status === 'ready' && !group.findings.length && (
        <article className="bench-finding">
          <strong>{NOTHING_OUT_OF_RANGE}</strong>
          <p>No open findings for {group.label}.</p>
        </article>
      )}
      {severityGroups(group.findings).map((severity) => (
        <SeverityBlock
          key={severity.severity}
          projectId={projectId}
          group={severity}
          onChanged={onChanged}
        />
      ))}
      <CouldNotCheck projectId={projectId} robotId={group.robotId} />
    </section>
  )
}

/** Critical and warning findings stay open; infos (checker infos among them) start collapsed,
 *  so however many there are they never push an observer finding off the pane. */
function SeverityBlock({
  projectId,
  group,
  onChanged
}: {
  projectId: string
  group: SeverityGroup
  onChanged: () => void
}): React.JSX.Element {
  const heading = (
    <>
      {group.severity.toUpperCase()} · {group.count} · last seen{' '}
      <time dateTime={group.lastSeen} title={group.lastSeen}>
        {relativeTime(group.lastSeen)}
      </time>
    </>
  )
  const cards = group.findings.map((finding) => (
    <FindingCard key={finding.id} projectId={projectId} finding={finding} onChanged={onChanged} />
  ))
  if (group.severity === 'info')
    return (
      <details>
        <summary className="bench-section-heading">{heading}</summary>
        {cards}
      </details>
    )
  return (
    <div>
      <p className="bench-section-heading">{heading}</p>
      {cards}
    </div>
  )
}

function OpenedFinding({
  projectId,
  findingId,
  onClose,
  onChanged
}: {
  projectId: string
  findingId: string
  onClose?: () => void
  onChanged: () => void
}): React.JSX.Element {
  const { finding, failed } = useSelectedFinding(projectId, findingId)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: 'nearest' })
  }, [findingId])
  return (
    <section ref={ref} aria-label="Opened finding">
      <button type="button" className="bench-text-button" onClick={onClose}>
        Close
      </button>
      {failed && <p role="alert">This finding is unavailable.</p>}
      {!failed && !finding && <p role="status">Opening the finding…</p>}
      {finding && (
        <FindingCard
          key={finding.id}
          projectId={projectId}
          finding={finding}
          defaultOpen
          onChanged={onChanged}
        />
      )}
    </section>
  )
}

type Unchecked =
  | { status: 'closed' | 'loading' | 'failed' }
  | { status: 'ready'; signals: string[] | null }

/** What the rules could not judge on this robot, read from its `missing_signals` only when the
 *  person opens the disclosure. */
function CouldNotCheck({
  projectId,
  robotId
}: {
  projectId: string
  robotId: string
}): React.JSX.Element {
  const [state, setState] = useState<Unchecked>({ status: 'closed' })
  async function load(): Promise<void> {
    setState({ status: 'loading' })
    try {
      setState({ status: 'ready', signals: await loadMissingSignals(projectId, robotId) })
    } catch {
      setState({ status: 'failed' })
    }
  }
  return (
    <div>
      <button
        type="button"
        className="bench-text-button"
        aria-expanded={state.status !== 'closed'}
        onClick={() => (state.status === 'closed' ? void load() : setState({ status: 'closed' }))}
      >
        Could not check
      </button>
      {state.status === 'loading' && <p role="status">Reading what could not be checked…</p>}
      {state.status === 'failed' && <p role="alert">What could not be checked is unavailable.</p>}
      {state.status === 'ready' && <UncheckedList signals={state.signals} />}
    </div>
  )
}

function UncheckedList({ signals }: { signals: string[] | null }): React.JSX.Element {
  if (signals === null)
    return <p>Not assessed yet: the rules list what they cannot judge once they have run.</p>
  if (!signals.length) return <p>Every signal and fact the rules need was there.</p>
  return (
    <ul aria-label="Could not check">
      {signals.map((signal) => (
        <li key={signal}>{signal}</li>
      ))}
    </ul>
  )
}
