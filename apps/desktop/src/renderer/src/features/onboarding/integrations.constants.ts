// Connector catalog for the onboarding "Connect your tools" step. Ported from
// window.INTEGRATIONS in TestDesign/app/data.js. The five connector types match
// the Integrations feature area (CLAUDE.md §2.1) and API.md §2.5's catalog.
// `steps` / `result` are the simulated connect animation copy for this prototype.

export interface Integration {
  readonly id: string
  readonly name: string
  readonly kind: string
  /** Short monogram shown in the tile. */
  readonly mark: string
  readonly steps: readonly string[]
  readonly result: string
}

export const INTEGRATIONS: readonly Integration[] = [
  {
    id: 'github',
    name: 'GitHub',
    kind: 'Code',
    mark: 'GH',
    steps: [
      'Authorizing with GitHub…',
      'Cloning strider-fw, strider-tools…',
      'Indexing 214 files…'
    ],
    result: 'Connected — 2 repos, 214 files, 31k LOC indexed'
  },
  {
    id: 'kicad',
    name: 'KiCad',
    kind: 'PCB / Schematic',
    mark: 'Ki',
    steps: ['Watching project folder…', 'Parsing strider_main.kicad_sch…', 'Extracting netlist…'],
    result: 'Connected — 47 components, 16 nets, 3 ICs'
  },
  {
    id: 'onshape',
    name: 'Onshape',
    kind: 'Mechanical CAD',
    mark: 'On',
    steps: ['Authorizing with Onshape…', 'Loading Strider workspace…', 'Reading 12 assemblies…'],
    result: 'Connected — 12 assemblies, 84 parts, 6 mates'
  },
  {
    id: 'ros',
    name: 'ROS 2',
    kind: 'Runtime',
    mark: 'R2',
    steps: ['Discovering domain 42…', 'Listening to /rosout…', 'Mapping node graph…'],
    result: 'Connected — 9 nodes, 23 topics live'
  }
]

export interface TemplateRobot {
  readonly id: string
  readonly name: string
  readonly sub: string
  readonly body: string
}

export const TEMPLATE_ROBOTS: readonly TemplateRobot[] = [
  { id: 'quad', name: 'Quadruped', sub: '12 actuators · IMU · CAN FD', body: 'M12' },
  { id: 'rover', name: 'Diff-drive rover', sub: '2 motors · lidar · IMU', body: 'M2' },
  { id: 'arm', name: 'Robot arm', sub: '6 DOF · servo bus · gripper', body: 'M6' },
  { id: 'drone', name: 'Quadcopter', sub: '4 ESCs · GPS · baro', body: 'M4' }
]

/** Build-log lines shown while the context model is assembled (simulated). */
export const BUILD_LOG_LINES: readonly (readonly [string, string])[] = [
  ['Parsing strider_main.kicad_sch', '47 components · 16 nets'],
  ['Indexing strider-fw', '214 files · 31k LOC'],
  ['Reading Onshape assemblies', '12 assemblies · 84 parts'],
  ['Mapping ROS 2 node graph', '9 nodes · 23 topics'],
  ['Resolving cross-domain links', '31 links found'],
  ['Checking integration contracts', '2 issues flagged']
]

export const MIN_SOURCES_TO_BUILD = 2
