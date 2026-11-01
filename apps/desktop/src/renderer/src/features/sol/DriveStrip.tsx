// SOLUSDEV-319 drive slice 3: the A3 strip (docs/architecture/sol-drive.md §5
// "While a step runs") — `DRIVING <APP> · STEP k OF N`, a progress bar and
// Stop, while an approved drive.step's output is incomplete. Every word here
// is Solus-authored except the app name (slice 4: the step's, else the pill's
// window-bound snapshot, else KiCad), rendered as plain text, upper-cased and
// cut to 24 characters; the step's output only supplies k and N (driveProgress).
// It tells main a step runs (amber outline, quiet gestures) and that it ended.
// Stop needs no route: the helper's kill switch takes the click as physical
// input and pauses the step at its next act. Until the run's status arrives the
// strip says STOPPING (bar frozen) and main keeps the outline and the quiet
// gesture period — the step is not over until then.
import { useEffect, useState } from 'react'
import { getDriveBridge, type DriveBridge } from '../../lib/driveBridge'
import type { CommandRun } from './commandRuns'
import { latestDriveProgress, type DriveProgress } from './driveProgress'
import { useSolWindowStore } from './solWindowStore'
import './DriveStrip.css'

export interface DriveStripProps {
  readonly run: CommandRun
  readonly bridge?: DriveBridge | null
  /** The driven app's name when the caller knows it from the step. */
  readonly appName?: string
}

const KICAD = 'KiCad'
const APP_LABEL_MAX = 24

/** The app the strip names: the step's, else the window-bound app the pill
 *  was summoned over, else KiCad (project-bound steps). Untrusted text. */
function useAppName(explicit: string | undefined): string {
  const front = useSolWindowStore((s) => s.frontApp)
  if (explicit) return explicit
  return front?.drivable && front.binding === 'window' ? front.name : KICAD
}

const appLabel = (name: string): string => [...name.toUpperCase()].slice(0, APP_LABEL_MAX).join('')

function tellMain(bridge: DriveBridge | null, active: boolean): void {
  // A lost message only costs the outline; main clears it on its own after 150 s.
  void bridge?.setDriving(active).catch(() => undefined)
}

function labelOf(app: string, progress: DriveProgress | null, stopping: boolean): string {
  const lead = `DRIVING ${appLabel(app)}`
  if (stopping) return `${lead} · STOPPING…`
  return progress ? `${lead} · STEP ${progress.step} OF ${progress.total}` : `${lead} · STARTING`
}

export function DriveStrip({
  run,
  bridge = getDriveBridge(),
  appName
}: DriveStripProps): React.JSX.Element | null {
  // Stop freezes the progress shown at the click (undefined: not stopped).
  const [frozen, setFrozen] = useState<DriveProgress | null | undefined>(undefined)
  const active = run.status === null
  const app = useAppName(appName)
  useEffect(() => {
    if (!active) return
    tellMain(bridge, true)
    return () => tellMain(bridge, false)
  }, [active, bridge])
  if (!active) return null
  const stopping = frozen !== undefined
  const progress = stopping ? frozen : latestDriveProgress(run.text)
  const percent = progress ? (progress.step / progress.total) * 100 : 0
  return (
    <div className="drive-strip" role="status" aria-label={`SOL is driving ${app}`}>
      <div className="drive-strip__line">
        <span className="drive-strip__label">{labelOf(app, progress, stopping)}</span>
        <button
          type="button"
          className="drive-strip__stop"
          disabled={stopping}
          onClick={() => setFrozen(latestDriveProgress(run.text))}
        >
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
