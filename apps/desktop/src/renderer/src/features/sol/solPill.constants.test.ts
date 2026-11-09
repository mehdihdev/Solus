// SOLUSDEV-319: the renderer's mirror of main's pill height cap — the two must
// agree or the thread would be clipped instead of scrolling inside.
import { describe, it, expect } from 'vitest'
import {
  SOL_PILL_MAX_HEIGHT as MAIN_MAX,
  SOL_PILL_MAX_SCREEN_FRACTION as MAIN_FRACTION
} from '../../../../main/sol-window/pillGeometry'
import {
  SOL_PILL_MAX_HEIGHT_PX,
  SOL_PILL_MAX_SCREEN_FRACTION,
  pillHeightCap
} from './solPill.constants'

describe('pill height cap (renderer side)', () => {
  it('mirrors main exactly', () => {
    expect(SOL_PILL_MAX_HEIGHT_PX).toBe(MAIN_MAX)
    expect(SOL_PILL_MAX_SCREEN_FRACTION).toBe(MAIN_FRACTION)
  })

  it('is min(620, 60% of the available screen height)', () => {
    expect(pillHeightCap(1040)).toBe(620)
    expect(pillHeightCap(800)).toBe(480)
    expect(pillHeightCap(Number.NaN)).toBe(620)
  })
})
