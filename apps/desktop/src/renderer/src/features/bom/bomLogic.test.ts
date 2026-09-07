// SOLUSDEV-246 / STORE ST4 — the BOM page's pure presentation rules.
import { describe, it, expect } from 'vitest'
import {
  EMPTY_ADD_ROW_FORM,
  csvFilename,
  formatMoney,
  itemInputFrom,
  sourcesLine,
  stateColor,
  totalsLine,
  viewNote
} from './bomLogic'
import { bomView, designRow } from './testing/fixtures'

describe('bomLogic', () => {
  it('formats money in the configured currency and dashes the unknown', () => {
    expect(formatMoney(null, 'USD')).toBe('—')
    expect(formatMoney(12.5, 'USD')).toMatch(/12\.50/)
    expect(formatMoney(3, 'not-a-currency')).toBe('3.00 not-a-currency')
  })

  it('names where a design row was observed', () => {
    expect(sourcesLine(designRow())).toBe('electrical: U3 · mechanical: Servo body')
  })

  it('summarises totals, including the cost-target verdict only when there is a target', () => {
    expect(totalsLine(bomView())).toMatch(/^2 rows · 1 priced · total .*29\.00/)
    expect(totalsLine(bomView())).not.toMatch(/target/)
    const capped = bomView({
      config: { preferred_suppliers: [], cost_target: 20, currency: 'USD' }
    })
    expect(
      totalsLine({ ...capped, totals: { ...capped.totals, cost_target: 20, over_target: true } })
    ).toMatch(/over target/)
  })

  it('colours states and notes truncation', () => {
    expect(stateColor('installed')).toBe('var(--ok)')
    expect(stateColor('planned')).toBe('var(--warn)')
    expect(viewNote(bomView())).toBeNull()
    expect(viewNote(bomView({ truncated: true }))).toMatch(/bounded subset/)
  })

  it('derives a safe CSV filename', () => {
    expect(csvFilename('Rover MK3 / v2')).toBe('bom-rover-mk3-v2.csv')
    expect(csvFilename('///')).toBe('bom-project.csv')
  })
})

describe('itemInputFrom', () => {
  const form = { ...EMPTY_ADD_ROW_FORM, name: 'Motor' }
  it('sends only the fields the user filled in', () => {
    expect(itemInputFrom(form)).toEqual({ name: 'Motor', category: 'purchase', quantity: 1 })
    expect(
      itemInputFrom({
        ...form,
        quantity: '',
        unitCost: '3.5',
        supplier: ' Mouser ',
        partNumber: 'X1'
      })
    ).toEqual({
      name: 'Motor',
      category: 'purchase',
      unit_cost: 3.5,
      supplier: 'Mouser',
      part_number: 'X1'
    })
  })
  it('explains the first problem instead of sending', () => {
    expect(itemInputFrom({ ...form, name: '  ' })).toEqual({ error: 'Give the row a name.' })
    expect(itemInputFrom({ ...form, quantity: '0' })).toMatchObject({
      error: expect.stringMatching(/Quantity/)
    })
    expect(itemInputFrom({ ...form, quantity: '1.5' })).toMatchObject({
      error: expect.stringMatching(/Quantity/)
    })
    expect(itemInputFrom({ ...form, unitCost: '-1' })).toMatchObject({
      error: expect.stringMatching(/Unit cost/)
    })
  })
})
