// SOLUSDEV-246 / STORE ST4 — BOM API-shaped fixtures. Test data only.
import type { BomRowApi, BomViewApi } from '../../../lib/api/resources.bom'

export function designRow(over: Partial<BomRowApi> = {}): BomRowApi {
  return {
    key: 'canonical:00000000-0000-7000-8000-000000000009',
    kind: 'design',
    name: 'MG996R',
    part_number: 'MG996R',
    manufacturer: 'TowerPro',
    quantity: 1,
    state: 'installed',
    supplier: null,
    unit_cost: null,
    line_cost: null,
    notes: null,
    sources: [
      { entity_id: 'e2', kind: 'component', domain: 'electrical', name: 'U3' },
      { entity_id: 'e1', kind: 'part', domain: 'mechanical', name: 'Servo body' }
    ],
    item_id: null,
    canonical_id: '00000000-0000-7000-8000-000000000009',
    ...over
  }
}

export function purchaseRow(over: Partial<BomRowApi> = {}): BomRowApi {
  return {
    key: 'item:00000000-0000-7000-8000-000000000001',
    kind: 'purchase',
    name: 'NEMA 17 stepper',
    part_number: '17HS4401',
    manufacturer: null,
    quantity: 2,
    state: 'planned',
    supplier: 'StepperOnline',
    unit_cost: 14.5,
    line_cost: 29,
    notes: null,
    sources: [],
    item_id: '00000000-0000-7000-8000-000000000001',
    canonical_id: null,
    ...over
  }
}

export function bomView(over: Partial<BomViewApi> = {}): BomViewApi {
  return {
    slug: 'bom',
    rows: [designRow(), purchaseRow()],
    totals: { rows: 2, priced_rows: 1, line_cost_total: 29, cost_target: null, over_target: null },
    config: { preferred_suppliers: [], cost_target: null, currency: 'USD' },
    states: ['planned', 'ordered', 'received', 'installed', 'retired'],
    truncated: false,
    ...over
  }
}
