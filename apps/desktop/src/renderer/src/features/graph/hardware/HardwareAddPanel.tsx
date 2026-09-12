// The Hardware tab of the workspace Add panel (SOLUSDEV-250 P3,
// docs/wireflows/hardware-onboarding.md): Devices found · Search · Describe something
// new · Sourced, then the collapsed Unassigned parts. No card grid, no modals except the
// sourcing panel (SOLUSDEV-246 ST5) behind one button. Offline → one honest line and
// disabled controls; nothing is fabricated.
import { useState, type ReactNode } from 'react'
import { Button } from '../../../components/ui/Button'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { SourcingModal } from '../../sourcing/SourcingModal'
import { DescribeNew } from './DescribeNew'
import { DevicesFound } from './DevicesFound'
import { HARDWARE_COPY } from './hardware.constants'
import { HardwareSearch } from './HardwareSearch'
import { UnassignedParts } from './UnassignedParts'

export interface HardwareAddPanelProps {
  projectId: string
  online: boolean
  mode: SolMode
  /** Existing physical_robot entities — the targets every surface offers. */
  robots: readonly Entity[]
  /** The workspace's current entities (null = not loaded) — the device cards read bindings. */
  entities: readonly Entity[] | null
  onCreated: (entity: Entity) => void
}

const OFFLINE = 'Connect this project to add hardware.'
const BODY_STYLE = {
  fontSize: 12,
  color: 'var(--mut)',
  margin: '0 0 8px',
  lineHeight: 1.5
} as const
const HEADING_STYLE = {
  fontSize: 12.5,
  fontWeight: 600,
  color: 'var(--tx)',
  margin: '14px 0 4px'
} as const

function Section({ title, children }: { title: string; children: ReactNode }): React.JSX.Element {
  return (
    <section aria-label={title}>
      <h3 style={HEADING_STYLE}>{title}</h3>
      {children}
    </section>
  )
}

export function HardwareAddPanel({
  projectId,
  online,
  mode,
  robots,
  entities,
  onCreated
}: HardwareAddPanelProps): React.JSX.Element {
  const [sourcing, setSourcing] = useState(false)
  const disabled = !online
  return (
    <div className="hardware-add">
      <p style={BODY_STYLE}>{HARDWARE_COPY.intro[mode]}</p>
      {disabled && <p style={BODY_STYLE}>{OFFLINE}</p>}
      <Section title="Devices found">
        <p style={BODY_STYLE}>{HARDWARE_COPY.devices[mode]}</p>
        {online && (
          <DevicesFound
            projectId={projectId}
            mode={mode}
            robots={robots}
            entities={entities}
            onCreated={onCreated}
          />
        )}
      </Section>
      <Section title="Search">
        <p style={BODY_STYLE}>{HARDWARE_COPY.search[mode]}</p>
        <HardwareSearch
          projectId={projectId}
          robots={robots}
          onCreated={onCreated}
          disabled={disabled}
        />
      </Section>
      <Section title="Describe something new">
        <DescribeNew
          projectId={projectId}
          mode={mode}
          robots={robots}
          onCreated={onCreated}
          disabled={disabled}
        />
      </Section>
      <Section title="Sourced">
        <Button size="sm" disabled={disabled} onClick={() => setSourcing(true)}>
          Find a part from suppliers
        </Button>
      </Section>
      <UnassignedParts projectId={projectId} mode={mode} robots={robots} disabled={disabled} />
      {sourcing && (
        <SourcingModal
          projectId={projectId}
          door="workspace"
          onSelected={onCreated}
          onClose={() => setSourcing(false)}
        />
      )}
    </div>
  )
}
