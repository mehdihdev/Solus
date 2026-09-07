// Phase 6 proof (d) — the vitest twin of the Python vendor-hygiene ratchet
// (docs/architecture/hardware-onboarding.md §Generalisation proof): the desktop's shared
// hardware code names no vendor, board, bridge chip, tty path or sketch file. Word-boundary,
// case-insensitive, no allowlist — every hit is reported with its file:line.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const renderer = path.resolve(here, '../../..')
const SHARED_DIRS = [here, path.join(renderer, 'widgets/livebench/recognition')]
const VENDOR_WORDS =
  /\b(feetech|dynamixel|lerobot|sts3215|sts3250|scs0009|so-?10[01]|px4|pixhawk|odrive|myactuator|mavlink|unitree|ur5e?|arduino|teensy|esp32|ch343|cp210x|ft232|pl2303|xl330|xm430|robotis|ttyUSB|ttyACM)\b|\.ino\b/i

const sourceFiles = (dir: string): string[] =>
  fs
    .readdirSync(dir)
    .filter((name) => /\.tsx?$/.test(name) && !/\.test\./.test(name))
    .map((name) => path.join(dir, name))

const hits = (file: string): string[] =>
  fs
    .readFileSync(file, 'utf8')
    .split('\n')
    .flatMap((line, index) => {
      const match = VENDOR_WORDS.exec(line)
      return match
        ? [`${path.relative(renderer, file)}:${index + 1}: [${match[0]}] ${line.trim()}`]
        : []
    })

describe('vendor hygiene (desktop shared hardware code)', () => {
  it('sweeps a non-trivial set of files', () => {
    expect(SHARED_DIRS.flatMap(sourceFiles).length).toBeGreaterThanOrEqual(6)
  })

  it('names no vendor, board, bridge chip, tty path or sketch outside plugins', () => {
    const offenders = SHARED_DIRS.flatMap(sourceFiles).flatMap(hits)
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
