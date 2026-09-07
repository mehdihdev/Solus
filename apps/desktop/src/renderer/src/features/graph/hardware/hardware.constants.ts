// Add › Hardware surface data (SOLUSDEV-248 R1, docs/wireflows/hardware-onboarding.md).
// The five entry cards and the per-category spec fields for authored parts.
// Spec fields are generic to a category, never to a product family — a
// pneumatic valve, an ESC and a servo fill the same actuator fields. No vendor
// or product name appears in this directory.
import type { RobotCategory } from '../../../lib/api/hardware'
import type { SolMode } from '../../../store/settingsStore'

export type HardwareCardId = 'detected' | 'file' | 'library' | 'sourced' | 'authored'

export interface HardwareCard {
  id: HardwareCardId
  title: string
  /** One-line kind subtitle. */
  kind: string
  /** Status footer copy. */
  status: string
  /** Rendered aria-disabled with no modal (wireflow Flow 4). */
  disabled?: boolean
}

export const HARDWARE_CARDS: readonly HardwareCard[] = [
  { id: 'detected', title: 'Detected', kind: 'Devices on this machine', status: 'Enumerate' },
  {
    id: 'file',
    title: 'From a file',
    kind: 'Parts from connected sources',
    status: 'Assign parts'
  },
  {
    id: 'library',
    title: 'Library',
    kind: 'Curated parts and platforms',
    status: 'Search and import'
  },
  {
    id: 'sourced',
    title: 'Sourced',
    kind: 'Parts from suppliers',
    status: 'Sourcing (ST5) is not available yet.',
    disabled: true
  },
  { id: 'authored', title: 'Authored', kind: 'Describe a part yourself', status: 'Create a part' }
]

export interface HardwareSpecField {
  key: string
  label: string
  placeholder: string
  kind: 'text' | 'number'
}

export const HARDWARE_SPEC_FIELDS: Record<RobotCategory, readonly HardwareSpecField[]> = {
  sensors: [
    { key: 'interface', label: 'Interface', placeholder: 'I2C, SPI, analog, CAN…', kind: 'text' },
    { key: 'supply_v', label: 'Supply (V)', placeholder: '3.3', kind: 'number' },
    { key: 'range', label: 'Range', placeholder: '300–1250 hPa, ±16 g…', kind: 'text' },
    { key: 'resolution', label: 'Resolution', placeholder: '24-bit, 0.01 °C…', kind: 'text' }
  ],
  actuators: [
    {
      key: 'interface',
      label: 'Interface',
      placeholder: 'PWM, serial bus, CAN, pneumatic pilot…',
      kind: 'text'
    },
    { key: 'supply_v', label: 'Supply (V)', placeholder: '12', kind: 'number' },
    {
      key: 'rated_output',
      label: 'Rated output',
      placeholder: '30 A, 20 kg·cm, 200 L/min…',
      kind: 'text'
    },
    {
      key: 'control_signal',
      label: 'Control signal',
      placeholder: '50 Hz PWM, DShot600, 0–10 V…',
      kind: 'text'
    }
  ],
  controllers: [
    { key: 'mcu', label: 'MCU / SoC', placeholder: '32-bit MCU, RISC-V, SoC…', kind: 'text' },
    {
      key: 'interface',
      label: 'Interface',
      placeholder: 'USB, UART, CAN, Ethernet…',
      kind: 'text'
    },
    { key: 'supply_v', label: 'Supply (V)', placeholder: '5', kind: 'number' }
  ],
  end_effectors: [
    {
      key: 'mechanism',
      label: 'Mechanism',
      placeholder: 'parallel gripper, suction…',
      kind: 'text'
    },
    {
      key: 'actuation',
      label: 'Actuation',
      placeholder: 'servo, pneumatic, passive…',
      kind: 'text'
    },
    { key: 'interface', label: 'Interface', placeholder: 'PWM, serial bus, valve…', kind: 'text' }
  ],
  power: [
    {
      key: 'chemistry_or_type',
      label: 'Chemistry / type',
      placeholder: 'LiPo, LiFePO4, PSU, buck…',
      kind: 'text'
    },
    { key: 'voltage_v', label: 'Voltage (V)', placeholder: '11.1', kind: 'number' },
    { key: 'capacity', label: 'Capacity', placeholder: '5000 mAh, 150 W…', kind: 'text' }
  ],
  structure: [
    { key: 'material', label: 'Material', placeholder: 'aluminium, PETG, carbon…', kind: 'text' },
    { key: 'mass_g', label: 'Mass (g)', placeholder: '120', kind: 'number' }
  ],
  wiring: [
    {
      key: 'connector',
      label: 'Connector',
      placeholder: '2.54 mm header, bullet, screw terminal…',
      kind: 'text'
    },
    { key: 'gauge', label: 'Gauge', placeholder: '22 AWG', kind: 'text' },
    { key: 'length_mm', label: 'Length (mm)', placeholder: '300', kind: 'number' }
  ]
}

/** Copy per SOL mode (ADR-016). Live claims — device titles, errors — are never rephrased. */
export const HARDWARE_COPY: Record<
  'intro' | 'detected' | 'noDevices' | 'proposal' | 'file' | 'library' | 'authored',
  Record<SolMode, string>
> = {
  intro: {
    Guide:
      'Add hardware to a Physical Robot. Detected devices, parts from your connected sources, ' +
      'the library and hand-authored parts all land under the robot’s seven categories.',
    Expert: 'Add hardware under a Physical Robot’s categories.'
  },
  detected: {
    Guide:
      'These are the devices Solus can see on this machine right now, named only as far as the ' +
      'evidence goes — a bridge chip never implies the board behind it.',
    Expert: 'Devices on this machine, named to the level known.'
  },
  noDevices: {
    Guide:
      'No devices detected. Plug in a USB device or CAN adapter, or join the robot’s network, ' +
      'then reopen this list.',
    Expert: 'No devices detected. Check USB, CAN adapter or network, then reopen.'
  },
  proposal: {
    Guide:
      'Solus interrogated the device safely (ping and listen only) and lists what answered. ' +
      'Each row is a proposal with its evidence — accept, rename or reject it. Confirm writes ' +
      'the robot, its parts and config, then opens a bench session; nothing is written before.',
    Expert: 'Rows are proposals. Confirm writes robot, parts, config and opens a session.'
  },
  file: {
    Guide:
      'Parts from your connected CAD, schematic and BOM sources that no robot owns yet. Pick ' +
      'the ones that belong to a robot and the category they go under — their source identity ' +
      'and cross-domain edges stay as they are.',
    Expert: 'Unassigned connector parts. Select, pick robot and category, attach.'
  },
  library: {
    Guide:
      'Curated parts and whole platforms with their specs and configs. Search, preview a ' +
      'definition, then import a part under one of a robot’s categories or a platform as a new ' +
      'robot — every imported value is marked as coming from the library.',
    Expert: 'Search, preview, import a part into a robot or a platform as a new robot.'
  },
  authored: {
    Guide:
      'Describe a part in your own words. Pick the robot it belongs to (or start a new one), its ' +
      'category, and the key specs that fit — every field is optional except the name.',
    Expert: 'Name, robot, category, specs, lifecycle. Only the name is required.'
  }
}
