// SOLUSDEV-246 (STORE ST5) — pure rules for the sourcing panel: the describe
// form → a request body, the torque sentence, grounding labels, the trade-off
// line, and the side-by-side comparison rows. No fetch, no store.
import type {
  CandidateApi,
  SourcingDoor,
  SourcingRequestInput,
  SourcingRulesApi,
  TorqueApi
} from '../../lib/api/resources.sourcing'

export interface SpecForm {
  text: string
  loadKg: string
  armM: string
  protocol: string
  voltageV: string
  partClass: string
}

export const EMPTY_SPEC_FORM: SpecForm = {
  text: '',
  loadKg: '',
  armM: '',
  protocol: '',
  voltageV: '',
  partClass: 'motor'
}

export interface RequestContext {
  door: SourcingDoor
  assemblyId?: string
  masses?: Record<string, number>
  safetyFactor?: number
  preferences?: Record<string, string>
}

function optionalNumber(raw: string): number | undefined | 'bad' {
  const trimmed = raw.trim()
  if (trimmed === '') return undefined
  const value = Number(trimmed)
  return Number.isFinite(value) && value >= 0 ? value : 'bad'
}

/** The request body from the form, or a message when it cannot be one. */
export function requestInputFrom(
  form: SpecForm,
  context: RequestContext
): SourcingRequestInput | { error: string } {
  const load = optionalNumber(form.loadKg)
  const arm = optionalNumber(form.armM)
  const voltage = optionalNumber(form.voltageV)
  if (load === 'bad') return { error: 'Load must be a number of kilograms.' }
  if (arm === 'bad') return { error: 'Arm must be a number of metres.' }
  if (voltage === 'bad') return { error: 'Voltage must be a number of volts.' }
  if ((load === undefined) !== (arm === undefined)) {
    return {
      error:
        load === undefined
          ? 'Give the load in kilograms too.'
          : 'Give the arm length in metres too.'
    }
  }
  const text = form.text.trim()
  if (!text && load === undefined && !context.assemblyId) {
    return { error: 'Describe the requirement, give a load and arm, or pick an assembly.' }
  }
  const spec: SourcingRequestInput['spec'] = {
    text,
    ...(form.protocol.trim() ? { protocol: form.protocol.trim() } : {}),
    ...(voltage !== undefined ? { voltage_v: voltage } : {}),
    part_class: form.partClass.trim() || 'motor'
  }
  return {
    door: context.door,
    spec,
    ...(context.assemblyId ? { assembly_entity_id: context.assemblyId } : {}),
    ...(context.masses && Object.keys(context.masses).length > 0 ? { masses: context.masses } : {}),
    ...(load !== undefined && arm !== undefined ? { load_kg: load, arm_m: arm } : {}),
    ...(context.safetyFactor !== undefined ? { safety_factor: context.safetyFactor } : {}),
    ...(context.preferences ? { preferences: context.preferences } : {})
  }
}

const nm = (value: number): string => `${value.toFixed(2)} N·m`

export function torqueLine(torque: TorqueApi): string {
  const head = `Required ${nm(torque.required_torque_nm)} (static ${nm(torque.static_torque_nm)} × ${torque.safety_factor} safety)`
  const from = torque.assembly ? ` from ${torque.assembly}` : ''
  const unknown = torque.unknown.length > 0 ? ` · not included: ${torque.unknown.join(', ')}` : ''
  return `${head}${from}${unknown}`
}

export function groundingLabel(candidate: CandidateApi): 'CITED' | 'UNVERIFIED' {
  return candidate.grounding === 'cited' ? 'CITED' : 'UNVERIFIED'
}

export function tradeOffLine(candidate: CandidateApi): string {
  return `Optimises for ${candidate.optimizes_for} · gives up ${candidate.gives_up}`
}

export function safeHttps(url: string | null | undefined): string | null {
  if (!url || !url.startsWith('https://') || /\s/.test(url)) return null
  return url
}

function money(value: number | null, currency: string | null, fallback: string): string {
  if (value === null) return '—'
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency ?? fallback
    }).format(value)
  } catch {
    return `${value.toFixed(2)} ${currency ?? fallback}`
  }
}

export interface CompareRow {
  label: string
  values: string[]
}

/** One row per attribute, one column per candidate; unknown is a dash. */
export function compareColumns(
  candidates: readonly CandidateApi[],
  currency: string
): CompareRow[] {
  const dash = (v: string | number | null, unit = ''): string =>
    v === null || v === undefined ? '—' : `${typeof v === 'number' ? v : v}${unit}`
  return [
    { label: 'Torque', values: candidates.map((c) => dash(c.torque_nm, ' N·m')) },
    { label: 'Price', values: candidates.map((c) => money(c.cost, c.currency, currency)) },
    { label: 'Weight', values: candidates.map((c) => dash(c.weight_kg, ' kg')) },
    { label: 'Protocol', values: candidates.map((c) => dash(c.protocol)) },
    { label: 'Voltage', values: candidates.map((c) => dash(c.voltage_v, ' V')) },
    { label: 'Availability', values: candidates.map((c) => dash(c.availability)) },
    { label: 'Supplier', values: candidates.map((c) => dash(c.supplier ?? c.manufacturer)) },
    {
      label: 'Certifications',
      values: candidates.map((c) => (c.certifications.length ? c.certifications.join(', ') : '—'))
    }
  ]
}

/** Typed mass overrides from the form's text fields; blanks and non-numbers are left out. */
export function massesFrom(text: Readonly<Record<string, string>>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [id, raw] of Object.entries(text)) {
    const value = Number(raw.trim())
    if (raw.trim() !== '' && Number.isFinite(value) && value >= 0) out[id] = value
  }
  return out
}

/** `"Acme Motors: export controlled; Foo"` → typed entries (the repo table's own syntax). */
export function excludedFrom(raw: string): SourcingRulesApi['excluded_suppliers'] {
  return raw
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const [name, ...rest] = entry.split(':')
      const reason = rest.join(':').trim()
      return {
        name: (name ?? '').trim(),
        reason: reason || "Excluded by the project's .solus rules"
      }
    })
    .filter((e) => e.name)
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

/** One line naming the effective rules, for the requirement step. */
export function rulesSummary(rules: SourcingRulesApi | null): string {
  if (!rules) return 'Loading rules…'
  const parts = [
    rules.excluded_suppliers.length > 0 &&
      plural(rules.excluded_suppliers.length, 'excluded supplier'),
    rules.required_certifications.length > 0 &&
      `requires ${rules.required_certifications.join(', ')}`,
    rules.max_voltage_v !== null && `max ${rules.max_voltage_v} V`,
    rules.allowed_protocols.length > 0 && `protocols ${rules.allowed_protocols.join(', ')}`
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : 'No rules set'
}

export interface CategoryOption {
  id: string
  label: string
}

/** Motors land in "Actuators / motors" unless the user says otherwise; else the first category. */
export function defaultCategory(categories: readonly CategoryOption[]): string {
  const actuators = categories.find((c) => /^actuators/i.test(c.label))
  return (actuators ?? categories[0])?.id ?? ''
}
