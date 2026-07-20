// Connector display metadata for the onboarding "Connect your tools" step.
// Only providers with a REAL drivable connect flow are curated here
// (SOLUSDEV-152 de-simulation): GitHub (OAuth bridge) and KiCad
// (committed-export file pick). Providers the backend registry does not
// register (Onshape, ROS 2) are not offered — their tiles return when their
// real connectors land.

export interface Integration {
  readonly id: string
  readonly name: string
  readonly kind: string
  /** Short monogram shown in the tile. */
  readonly mark: string
}

export const INTEGRATIONS: readonly Integration[] = [
  { id: 'github', name: 'GitHub', kind: 'Code', mark: 'GH' },
  { id: 'kicad', name: 'KiCad', kind: 'PCB / Schematic — committed netlist export', mark: 'Ki' }
]

export const MIN_SOURCES_TO_BUILD = 2
