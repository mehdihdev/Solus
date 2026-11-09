// Settings › SOL: "SOL can use your mouse and keyboard" (SOLUSDEV-319 drive
// slice 3, docs/architecture/sol-drive.md §5). Off by default. Unavailable
// greys the switch and says why in one sentence; a missing helper grant is
// tagged here, and its fix is the Needs-attention card (like screen capture).
// Slice 3b: an agent awaiting Login Items approval is tagged the same way; a
// missing helper gets one muted sentence (reinstall), with no card.
import { Switch } from '../../../components/ui/Switch'
import { Row, InlineError, StatusTag } from '../settingsUi'
import {
  DRIVE_COPY,
  DRIVE_LABEL,
  DRIVE_NOT_FOUND_COPY,
  DRIVE_REASON_COPY,
  driveBlocked,
  driveHelperMissing,
  driveNeedsApproval
} from '../driveCopy'
import type { DriveSettings } from '../useDriveStatus'

const FIX_LINK: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  color: 'var(--acc)',
  fontSize: 11.5,
  fontFamily: 'var(--font-ui)'
}

/** The tag a blocked row carries; approval comes first (the agent must run). */
function blockTag(status: DriveSettings['status']): string | null {
  if (driveNeedsApproval(status)) return 'Needs approval'
  return driveBlocked(status) ? 'Permission needed' : null
}

function DriveLabel({
  tag,
  dev,
  onFix
}: {
  tag: string | null
  dev: boolean
  onFix: () => void
}): React.JSX.Element {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {DRIVE_LABEL}
      {dev && <StatusTag tone="mut">Development build</StatusTag>}
      {tag && (
        <span
          className="settings-row-in"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
        >
          <StatusTag tone="warn">{tag}</StatusTag>
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
  const unavailable = status.available || !status.reason ? null : DRIVE_REASON_COPY[status.reason]
  const reason = unavailable ?? (driveHelperMissing(status) ? DRIVE_NOT_FOUND_COPY : null)
  return (
    <>
      <Row
        label={<DriveLabel tag={blockTag(status)} dev={status.unsignedDev} onFix={onFix} />}
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
