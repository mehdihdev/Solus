import { AlertScreen } from '@solus/desktop'

const noop = (): void => {}

const wide = {
  display: 'flex',
  flexDirection: 'column',
  height: 460,
  width: 820,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
} as const

const panel = {
  display: 'flex',
  flexDirection: 'column',
  height: 460,
  width: 460,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
} as const

export function FullWidth() {
  return (
    <div style={wide}>
      <AlertScreen onBack={noop} />
    </div>
  )
}

export function SidePanelWidth() {
  return (
    <div style={panel}>
      <AlertScreen onBack={noop} />
    </div>
  )
}
