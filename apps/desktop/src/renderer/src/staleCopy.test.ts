// SOLUSDEV-250 P1 — the copy twin of features/graph/hardware/vendorHygiene.test.ts:
// the renderer names no retired surface ('Sources' screen/page, "pick this device")
// and no pre-rename product term ('Context Model'). Every hit is reported file:line.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const renderer = path.dirname(fileURLToPath(import.meta.url))
const STALE = /sources screen|sources page|pick this device|context model/i

const sourceFiles = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return /\.tsx?$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : []
  })

const hits = (file: string): string[] =>
  fs
    .readFileSync(file, 'utf8')
    .split('\n')
    .flatMap((line, index) => {
      const match = STALE.exec(line)
      return match
        ? [`${path.relative(renderer, file)}:${index + 1}: [${match[0]}] ${line.trim()}`]
        : []
    })

describe('stale copy (renderer)', () => {
  it('sweeps a non-trivial set of files', () => {
    expect(sourceFiles(renderer).length).toBeGreaterThanOrEqual(50)
  })

  it('names no retired screen or pre-rename product term', () => {
    const offenders = sourceFiles(renderer).flatMap(hits)
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
