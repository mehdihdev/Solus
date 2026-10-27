// SOLUSDEV-319 drive slice 3: the A3 strip (docs/architecture/sol-drive.md §5
// "While a step runs") — `DRIVING KICAD · STEP k OF N`, a progress bar and
// Stop, while an approved drive.step's output is incomplete. Every word here
// is Solus-authored; the step's output only supplies k and N (driveProgress).
// It tells main a step runs (amber outline, quiet gestures) and that it ended.
// Stop needs no route: the helper's kill switch takes the click as physical
// input and pauses the step — the strip and outline just clear at once.
import { useEffect, useState } from 'react'
import { getDriveBridge, type DriveBridge } from '../../lib/driveBridge'
import type { CommandRun } from './commandRuns'
import { latestDriveProgress } from './driveProgress'
import './DriveStrip.css'

export interface DriveStripProps {
  readonly run: CommandRun
  readonly bridge?: DriveBridge | null
}

function tellMain(bridge: DriveBridge | null, active: boolean): void {
  // A lost message only costs the outline; main clears it on its own after 150 s.
  void bridge?.setDriving(active).catch(() => undefined)
}

export function DriveStrip({
  run,
  bridge = getDriveBridge()
}: DriveStripProps): React.JSX.Element | null {
  const [stopped, setStopped] = useState(false)
  const active = run.status === null && !stopped
  useEffect(() => {
    if (!active) return
    tellMain(bridge, true)
    return () => tellMain(bridge, false)
  }, [active, bridge])
  if (!active) return null
  const progress = latestDriveProgress(run.text)
  const label = progress
    ? `DRIVING KICAD · STEP ${progress.step} OF ${progress.total}`
    : 'DRIVING KICAD · STARTING'
  const percent = progress ? (progress.step / progress.total) * 100 : 0
  return (
    <div className="drive-strip" role="status" aria-label="SOL is driving KiCad">
      <div className="drive-strip__line">
        <span className="drive-strip__label">{label}</span>
        <button type="button" className="drive-strip__stop" onClick={() => setStopped(true)}>
          Stop
        </button>
      </div>
      <div
        className="drive-strip__bar"
        role="progressbar"
        aria-label="Drive progress"
        aria-valuemin={0}
        aria-valuemax={progress?.total ?? 1}
        aria-valuenow={progress?.step ?? 0}
      >
        <div className="drive-strip__fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}
