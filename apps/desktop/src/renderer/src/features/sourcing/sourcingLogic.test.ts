// SOLUSDEV-246 (STORE ST5) — the sourcing panel's pure rules.
import { describe, it, expect } from 'vitest'
import {
  compareColumns,
  groundingLabel,
  requestInputFrom,
  safeHttps,
  torqueLine,
  tradeOffLine,
  EMPTY_SPEC_FORM
} from './sourcingLogic'
import { candidate, torque, unverified } from './testing/fixtures'

describe('requestInputFrom', () => {
  it('turns the describe form into a request, only with the fields given', () => {
    const input = requestInputFrom(
      { ...EMPTY_SPEC_FORM, text: 'holds 2 kg at 30 cm', loadKg: '2', armM: '0.3', voltageV: '24' },
      { door: 'bom' }
    )
    expect(input).toEqual({
      door: 'bom',
      spec: { text: 'holds 2 kg at 30 cm', voltage_v: 24, part_class: 'motor' },
      load_kg: 2,
      arm_m: 0.3
    })
  })
  it('carries the assembly and its supplied masses for the CAD door', () => {
    const input = requestInputFrom(
      { ...EMPTY_SPEC_FORM, text: '' },
      { door: 'workspace', assemblyId: 'asm-1', masses: { 'p-cam': 0.1 }, safetyFactor: 2 }
    )
    expect(input).toEqual({
      door: 'workspace',
      spec: { text: '', part_class: 'motor' },
      assembly_entity_id: 'asm-1',
      masses: { 'p-cam': 0.1 },
      safety_factor: 2
    })
  })
  it('refuses nonsense numbers with a message', () => {
    expect(requestInputFrom({ ...EMPTY_SPEC_FORM, loadKg: 'lots' }, { door: 'bom' })).toEqual({
      error: 'Load must be a number of kilograms.'
    })
    expect(requestInputFrom({ ...EMPTY_SPEC_FORM, loadKg: '2' }, { door: 'bom' })).toEqual({
      error: 'Give the arm length in metres too.'
    })
    expect(requestInputFrom({ ...EMPTY_SPEC_FORM, text: '' }, { door: 'bom' })).toEqual({
      error: 'Describe the requirement, give a load and arm, or pick an assembly.'
    })
  })
})

describe('presentation', () => {
  it('states the derived torque, the safety factor and what was left out', () => {
    expect(torqueLine(torque())).toBe(
      'Required 8.24 N·m (static 5.49 N·m × 1.5 safety) from Arm assembly · not included: Camera'
    )
    expect(torqueLine(torque({ unknown: [], assembly: undefined }))).toBe(
      'Required 8.24 N·m (static 5.49 N·m × 1.5 safety)'
    )
  })
  it('labels grounding honestly', () => {
    expect(groundingLabel(candidate())).toBe('CITED')
    expect(groundingLabel(unverified())).toBe('UNVERIFIED')
  })
  it('writes the trade-off sentence', () => {
    expect(tradeOffLine(candidate())).toBe('Optimises for torque per dollar · gives up weight')
  })
  it('compares side by side with dashes for unknowns and never a fabricated price', () => {
    const rows = compareColumns([candidate(), unverified()], 'USD')
    const price = rows.find((r) => r.label === 'Price')
    expect(price?.values).toEqual(['$24.90', '—'])
    const stock = rows.find((r) => r.label === 'Availability')
    expect(stock?.values).toEqual(['in stock', '—'])
    const torqueRow = rows.find((r) => r.label === 'Torque')
    expect(torqueRow?.values).toEqual(['1.26 N·m', '1.26 N·m'])
  })
  it('only https survives as a link', () => {
    expect(safeHttps('https://vendor.example/x.step')).toBe('https://vendor.example/x.step')
    expect(safeHttps('http://vendor.example/x.step')).toBeNull()
    expect(safeHttps('javascript:alert(1)')).toBeNull()
    expect(safeHttps(null)).toBeNull()
  })
})

describe('massesFrom / excludedFrom / rulesSummary', () => {
  it('keeps only finite non-negative masses, as typed', async () => {
    const { massesFrom } = await import('./sourcingLogic')
    expect(massesFrom({ a: '0.1', b: '', c: 'abc', d: '-1', e: ' 2 ' })).toEqual({ a: 0.1, e: 2 })
  })
  it('parses the repo table syntax for excluded suppliers', async () => {
    const { excludedFrom } = await import('./sourcingLogic')
    expect(excludedFrom('Acme Motors: export controlled; Foo; : nobody')).toEqual([
      { name: 'Acme Motors', reason: 'export controlled' },
      { name: 'Foo', reason: "Excluded by the project's .solus rules" }
    ])
  })
  it('summarises the effective rules on one line', async () => {
    const { rulesSummary } = await import('./sourcingLogic')
    expect(rulesSummary(null)).toBe('Loading rules…')
    expect(
      rulesSummary({
        excluded_suppliers: [],
        required_certifications: [],
        max_voltage_v: null,
        allowed_protocols: [],
        preferred_suppliers: []
      })
    ).toBe('No rules set')
    expect(
      rulesSummary({
        excluded_suppliers: [
          { name: 'A', reason: 'r' },
          { name: 'B', reason: 'r' }
        ],
        required_certifications: ['RoHS'],
        max_voltage_v: 24,
        allowed_protocols: ['CAN'],
        preferred_suppliers: []
      })
    ).toBe('2 excluded suppliers · requires RoHS · max 24 V · protocols CAN')
  })
})
