// Add › Hardware surface data (SOLUSDEV-250 P3, docs/wireflows/hardware-onboarding.md):
// the new-robot select option, the per-category spec fields (the sidebar's, later)
// and the copy per SOL mode. Spec fields are generic to a category, never to a
// product family — a pneumatic valve, an ESC and a servo fill the same actuator
// fields. No vendor or product name appears in this directory.
import type { RobotCategory } from '../../../lib/api/hardware'
import type { SolMode } from '../../../store/settingsStore'
import { MODAL_INPUT_STYLE } from '../../workspace/modals'

/** The "new Physical Robot" value in a robot select. */
/** Field chrome shared by every Add › Hardware input and select. */
export const FIELD_LABEL_STYLE = {
  display: 'block',
  marginTop: 12,
  fontSize: 11,
  color: 'var(--mut)'
} as const
export const FIELD_CONTROL_STYLE = { ...MODAL_INPUT_STYLE, marginTop: 4 } as const

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

/** Copy per SOL mode (ADR-016). Live claims — headlines, summaries, errors — are never rephrased. */
export const HARDWARE_COPY: Record<
  'intro' | 'devices' | 'search' | 'describe' | 'unassigned',
  Record<SolMode, string>
> = {
  intro: {
    Guide:
      'Everything here becomes part of a Physical Robot. A name is enough for a robot to exist ' +
      'and stream — the rest can follow.',
    Expert: 'Add hardware to a Physical Robot. A name is enough.'
  },
  devices: {
    Guide:
      'Devices this machine can see right now, named only as far as the evidence goes. Each ' +
      'card asks one question; nothing is added to your project until you confirm.',
    Expert: 'Devices on this machine, named to the level known. Nothing written before Add.'
  },
  search: {
    Guide:
      'Curated parts and platforms. A platform becomes a new robot; a part lands under a robot ' +
      'in its default category.',
    Expert: 'Library parts and platforms.'
  },
  describe: {
    Guide:
      'Name what you have. The category is guessed from the name — change it if it is wrong. ' +
      'Specs come later — from SOL, from a datasheet, or never.',
    Expert: 'Name it. Category guessed, changeable. Specs later.'
  },
  unassigned: {
    Guide:
      'Parts from your connected sources, and parts a deleted robot left behind, that no robot ' +
      'owns. Say which robot each belongs to.',
    Expert: 'Parts no robot owns. Pick robot and category.'
  }
}
