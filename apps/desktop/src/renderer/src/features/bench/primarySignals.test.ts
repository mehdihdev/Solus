import { expect, it } from 'vitest'
import { partitionSignals } from './primarySignals'

it('separates only explicitly declared diagnostics and retains unknown channels', () => {
  const rows = [
    { series: { signal: 'joint.position' } },
    { series: { signal: 'joint.temperature' } },
    { series: { signal: 'force', display_role: 'primary' } },
    { series: { signal: 'unknown', display_role: 'future-role' } },
    { series: { signal: 'health', display_role: 'diagnostic' } }
  ]
  expect(partitionSignals(rows)).toEqual({ primary: rows.slice(0, 4), diagnostics: [rows[4]] })
  expect(partitionSignals([])).toEqual({ primary: [], diagnostics: [] })
})
