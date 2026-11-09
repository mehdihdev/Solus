import { describe, it, expect } from 'vitest'
import { DRIVE_TOOL, isDriveTool, latestDriveProgress } from './driveProgress'

describe('latestDriveProgress (sol-drive.md §4 Progress)', () => {
  it('is null before any line', () => {
    expect(latestDriveProgress('')).toBeNull()
  })

  it('parses one complete line', () => {
    expect(latestDriveProgress('action 3/15 · click · 12.4 s\n')).toEqual({
      step: 3,
      total: 15,
      verb: 'click',
      seconds: 12.4
    })
  })

  it('takes the latest valid line', () => {
    const text = 'action 1/15 · click · 1.0 s\naction 2/15 · type · 3.5 s\n'
    expect(latestDriveProgress(text)?.step).toBe(2)
  })

  it('ignores lines that do not match the stable format', () => {
    const text =
      'action 2/15 · type · 3.5 s\nhello\naction 3/15 · Click · 4.0 s\naction 4/15 · key · 4 s\n<b>x</b>\n'
    expect(latestDriveProgress(text)?.step).toBe(2)
  })

  it('ignores an unterminated last line', () => {
    expect(
      latestDriveProgress('action 1/15 · click · 1.0 s\naction 2/15 · click · 2.0 s')?.step
    ).toBe(1)
  })

  it('rejects N = 0, k > N and k = 0', () => {
    expect(latestDriveProgress('action 0/0 · click · 1.0 s\n')).toBeNull()
    expect(latestDriveProgress('action 16/15 · click · 1.0 s\n')).toBeNull()
    expect(latestDriveProgress('action 0/15 · click · 1.0 s\n')).toBeNull()
  })

  it('keeps the previous valid line when a later one is out of range', () => {
    const text = 'action 5/15 · click · 1.0 s\naction 99/15 · click · 2.0 s\n'
    expect(latestDriveProgress(text)?.step).toBe(5)
  })

  it('does not tolerate padding or extra text', () => {
    expect(latestDriveProgress(' action 1/15 · click · 1.0 s\n')).toBeNull()
    expect(latestDriveProgress('action 1/15 · click · 1.0 s extra\n')).toBeNull()
  })

  it('names the drive tool', () => {
    expect(DRIVE_TOOL).toBe('drive.step')
    expect(isDriveTool('drive.step')).toBe(true)
    expect(isDriveTool('code.exec')).toBe(false)
  })
})
