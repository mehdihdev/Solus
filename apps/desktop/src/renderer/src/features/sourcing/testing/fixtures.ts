// SOLUSDEV-246 (STORE ST5) — sourcing API-shaped fixtures. Test data only.
import type {
  CandidateApi,
  SourcingRequestApi,
  SourcingRulesApi,
  TorqueApi
} from '../../../lib/api/resources.sourcing'

export function candidate(over: Partial<CandidateApi> = {}): CandidateApi {
  return {
    id: 'aaaaaaaaaaaaaaaa',
    name: 'NEMA 23 23HS22-2804S',
    manufacturer: 'StepperOnline',
    part_number: '23HS22-2804S',
    supplier: 'StepperOnline',
    torque_nm: 1.26,
    cost: 24.9,
    currency: 'USD',
    weight_kg: 0.7,
    protocol: 'step/dir',
    voltage_v: 24,
    availability: 'in stock',
    certifications: ['RoHS'],
    source_url: 'https://www.omc-stepperonline.com/23hs22-2804s',
    vendor_cad_url: 'https://www.omc-stepperonline.com/23hs22-2804s.step',
    optimizes_for: 'torque per dollar',
    gives_up: 'weight',
    notes: null,
    grounding: 'cited',
    flags: [],
    ...over
  }
}

export function unverified(over: Partial<CandidateApi> = {}): CandidateApi {
  return candidate({
    id: 'bbbbbbbbbbbbbbbb',
    name: 'Unknown brand servo',
    manufacturer: null,
    part_number: null,
    supplier: null,
    cost: null,
    currency: null,
    availability: null,
    source_url: null,
    vendor_cad_url: null,
    optimizes_for: 'cost',
    gives_up: 'provenance',
    grounding: 'unverified',
    flags: ['Voltage unknown (project maximum 24.0 V)'],
    ...over
  })
}

export function torque(over: Partial<TorqueApi> = {}): TorqueApi {
  return {
    static_torque_nm: 5.4915,
    required_torque_nm: 8.2373,
    safety_factor: 1.5,
    loads: [
      { name: 'Arm link', mass_kg: 1.2, lever_arm_m: 0.3 },
      { name: 'Gripper', mass_kg: 0.4, lever_arm_m: 0.5 }
    ],
    unknown: ['Camera'],
    assumptions: ['Static holding torque about the pivot.', 'Not included: Camera'],
    assembly: 'Arm assembly',
    assembly_entity_id: 'asm-1',
    parts: [
      { entity_id: 'p-link', name: 'Arm link', mass_kg: 1.2, position_mm: [300, 0, 50] },
      { entity_id: 'p-cam', name: 'Camera', mass_kg: null, position_mm: [100, 0, 0] }
    ],
    ...over
  }
}

export function rules(over: Partial<SourcingRulesApi> = {}): SourcingRulesApi {
  return {
    excluded_suppliers: [{ name: 'Acme Motors', reason: 'Export-controlled vendor' }],
    required_certifications: ['RoHS'],
    max_voltage_v: 24,
    allowed_protocols: [],
    preferred_suppliers: [],
    ...over
  }
}

export function request(over: Partial<SourcingRequestApi> = {}): SourcingRequestApi {
  return {
    id: 'req-1',
    project_id: 'p1',
    status: 'succeeded',
    door: 'workspace',
    spec: { text: 'actuator for the arm joint', protocol: 'step/dir', voltage_v: 24 },
    torque: torque(),
    assembly_entity_id: 'asm-1',
    candidates: [candidate(), unverified()],
    excluded: [
      {
        candidate: candidate({
          id: 'cccccccccccccccc',
          name: 'Acme MegaServo 40',
          supplier: 'Acme Motors',
          torque_nm: 4
        }),
        reasons: ["Supplier 'Acme Motors' is excluded: Export-controlled vendor"]
      }
    ],
    rules: rules(),
    model: 'claude-sonnet-5',
    error: null,
    job_id: 'job-1',
    selected_candidate_id: null,
    selected_entity_id: null,
    created_at: '2026-09-06T00:00:00Z',
    finished_at: '2026-09-06T00:00:10Z',
    ...over
  }
}
