import { Button, Card, LabeledSelect, Mono } from '@solus/desktop'

const noop = (): void => {}

const ROBOTS = [
  { value: 'ari-02', label: 'Ari-02' },
  { value: 'ari-01', label: 'Ari-01 (bench mule)' },
  { value: 'new', label: 'No robot yet — this becomes the robot.' }
] as const

const CATEGORIES = [
  { value: 'sensors', label: 'Sensors' },
  { value: 'actuators', label: 'Actuators / motors' },
  { value: 'controllers', label: 'Controllers' },
  { value: 'end_effectors', label: 'End effectors' },
  { value: 'power', label: 'Power' },
  { value: 'structure', label: 'Structure' },
  { value: 'wiring', label: 'Wiring' }
] as const

const LIFECYCLE = [
  { value: 'planned', label: 'Planned' },
  { value: 'ordered', label: 'Ordered' },
  { value: 'in_hand', label: 'In hand' },
  { value: 'installed', label: 'Installed' }
] as const

export function PartOf() {
  return (
    <div style={{ width: 320 }}>
      <LabeledSelect label="Part of" value="ari-02" options={ROBOTS} onChange={noop} />
    </div>
  )
}

export function Category() {
  return (
    <div style={{ width: 320 }}>
      <LabeledSelect label="Category" value="sensors" options={CATEGORIES} onChange={noop} />
    </div>
  )
}

export function Disabled() {
  return (
    <div style={{ width: 320 }}>
      <LabeledSelect label="Part of" value="ari-02" options={ROBOTS} onChange={noop} disabled />
      <LabeledSelect label="Category" value="power" options={CATEGORIES} onChange={noop} disabled />
    </div>
  )
}

export function InAddHardware() {
  return (
    <Card pad={20} style={{ width: 360 }}>
      <Mono>ADD › HARDWARE · OV9281 GLOBAL SHUTTER</Mono>
      <LabeledSelect label="Part of" value="ari-02" options={ROBOTS} onChange={noop} />
      <LabeledSelect label="Category" value="sensors" options={CATEGORIES} onChange={noop} />
      <LabeledSelect label="Lifecycle" value="ordered" options={LIFECYCLE} onChange={noop} />
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
        <Button kind="ghost" size="sm">
          Cancel
        </Button>
        <Button kind="primary" size="sm">
          Add to graph
        </Button>
      </div>
    </Card>
  )
}
