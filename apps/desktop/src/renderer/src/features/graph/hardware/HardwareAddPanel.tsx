import './hardware.css'
import { type ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { DescribeNew } from './DescribeNew'
import { DevicesFound } from './DevicesFound'
import { HardwareSearch } from './HardwareSearch'
import { useHardwareGeneration } from './useHardwareGeneration'
import { UnassignedParts } from './UnassignedParts'
import { HardwareSourcesPanel } from './HardwareSourcesPanel'

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
  margin: '8px 0 4px'
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
  const { authEpoch } = useHardwareGeneration(projectId)
  const disabled = !online
  return (
    <div className="hardware-add" key={`${projectId}:${authEpoch}`}>
      {disabled && <p style={BODY_STYLE}>{OFFLINE}</p>}
      <Section title="Devices found">
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
      {online && (
        <HardwareSourcesPanel
          projectId={projectId}
          mode={mode}
          title="Local configuration and calibration"
        />
      )}
      <Section title="Search">
        <HardwareSearch
          projectId={projectId}
          robots={robots}
          onCreated={onCreated}
          disabled={disabled}
          compact
        />
      </Section>
      <Section title="Describe something new">
        <DescribeNew
          projectId={projectId}
          mode={mode}
          robots={robots}
          onCreated={onCreated}
          disabled={disabled}
          compact
        />
      </Section>
      <UnassignedParts projectId={projectId} mode={mode} robots={robots} disabled={disabled} />
    </div>
  )
}
