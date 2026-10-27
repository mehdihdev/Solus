// SOLUSDEV-319 drive slice 3: the pill's reading of a drive.step's progress
// lines (docs/architecture/sol-drive.md §4 "Progress" — a stable format).
// Pure. The output is untrusted: only lines matching the format count, and
// nothing from it is shown except the two numbers it yields.

export const DRIVE_TOOL = 'drive.step'

const LINE = /^action (\d+)\/(\d+) · ([a-z]+) · (\d+\.\d) s$/

export interface DriveProgress {
  readonly step: number
  readonly total: number
  readonly verb: string
  readonly seconds: number
}

export function isDriveTool(tool: string): boolean {
  return tool === DRIVE_TOOL
}

function parseLine(line: string): DriveProgress | null {
  const match = LINE.exec(line)
  if (!match) return null
  const step = Number(match[1])
  const total = Number(match[2])
  if (!Number.isSafeInteger(total) || total < 1 || step < 1 || step > total) return null
  return { step, total, verb: match[3], seconds: Number(match[4]) }
}

/** The latest valid progress line; only `\n`-terminated lines count. */
export function latestDriveProgress(text: string): DriveProgress | null {
  const complete = text.split('\n').slice(0, -1)
  for (let i = complete.length - 1; i >= 0; i -= 1) {
    const progress = parseLine(complete[i])
    if (progress) return progress
  }
  return null
}
