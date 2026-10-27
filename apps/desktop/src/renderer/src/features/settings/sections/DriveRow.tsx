// Settings › SOL: "SOL can use your mouse and keyboard" (SOLUSDEV-319 drive
// slice 3, docs/architecture/sol-drive.md §5). Off by default. Unavailable
// greys the switch and says why in one sentence; a missing helper grant is
// tagged here, and its fix is the Needs-attention card (like screen capture).
import { Switch } from '../../../components/ui/Switch'
import { Row, InlineError, StatusTag } from '../settingsUi'
import { DRIVE_COPY, DRIVE_LABEL, DRIVE_REASON_COPY, driveBlocked } from '../driveCopy'
import type { DriveSettings } from '../useDriveStatus'

const FIX_LINK: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  color: 'var(--acc)',
  fontSize: 11.5,
  fontFamily: 'var(--font-ui)'
}

function DriveLabel({
  blocked,
  dev,
  onFix
}: {
  blocked: boolean
  dev: boolean
  onFix: () => void
}): React.JSX.Element {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {DRIVE_LABEL}
      {dev && <StatusTag tone="mut">Development build</StatusTag>}
      {blocked && (
        <span
          className="settings-row-in"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
        >
          <StatusTag tone="warn">Permission needed</StatusTag>
          <button type="button" onClick={onFix} className="interactive" style={FIX_LINK}>
            How to fix
          </button>
        </span>
      )}
    </span>
  )
}

export function DriveRow({
  drive,
  onFix
}: {
  drive: DriveSettings
  onFix: () => void
}): React.JSX.Element | null {
  const { status } = drive
  if (!status) return <InlineError message={drive.error} />
  const reason = status.available || !status.reason ? null : DRIVE_REASON_COPY[status.reason]
  return (
    <>
      <Row
        label={<DriveLabel blocked={driveBlocked(status)} dev={status.unsignedDev} onFix={onFix} />}
        description={
          <>
            {DRIVE_COPY}
            {reason && <span style={{ display: 'block', marginTop: 4 }}>{reason}</span>}
          </>
        }
      >
        <Switch
          ariaLabel={DRIVE_LABEL}
          checked={status.enabled}
          disabled={!status.available}
          onChange={drive.setDrive}
        />
      </Row>
      <InlineError message={drive.error} />
    </>
  )
}
