import { ContextMenu } from '@solus/desktop'

const noop = (): void => {}
const at = { position: 'relative', width: 380, height: 190 } as const

export function SectionMenu() {
  return (
    <div style={at}>
      <ContextMenu
        x={16}
        y={16}
        title="Code environment"
        items={[
          { label: 'Import files…', onSelect: noop },
          {
            label: 'Ask SOL to find…',
            onSelect: noop,
            disabled: true,
            hint: 'SOL is busy with another turn'
          },
          { label: 'Type it', onSelect: noop }
        ]}
        onClose={noop}
      />
    </div>
  )
}

export function EntryMenu() {
  return (
    <div style={at}>
      <ContextMenu
        x={16}
        y={16}
        title="imu_bno085.yaml"
        items={[
          { label: 'Edit', onSelect: noop },
          { label: 'Open in GitHub', onSelect: noop },
          { label: 'Delete', danger: true, onSelect: noop }
        ]}
        onClose={noop}
      />
    </div>
  )
}

export function ExtensionRailMenu() {
  return (
    <div style={at}>
      <ContextMenu
        x={16}
        y={16}
        title="KiCad BOM"
        items={[
          {
            label: 'Pin for all projects',
            onSelect: noop,
            disabled: true,
            hint: 'Developer registrations live on this machine only.'
          },
          { label: 'Open in Store', onSelect: noop }
        ]}
        onClose={noop}
      />
    </div>
  )
}

export function NodeActions() {
  return (
    <div style={{ position: 'relative', width: 380, height: 230 }}>
      <ContextMenu
        x={16}
        y={16}
        title="OV9281_IC"
        items={[
          { label: 'Explain with SOL', onSelect: noop },
          { label: 'Show neighbors in graph', onSelect: noop },
          {
            label: 'Unlink fingerprint match',
            onSelect: noop,
            disabled: true,
            hint: 'Confirmed by Priya Raman — ask an admin to unlink'
          },
          { label: 'Delete entity', danger: true, onSelect: noop }
        ]}
        onClose={noop}
      />
    </div>
  )
}
