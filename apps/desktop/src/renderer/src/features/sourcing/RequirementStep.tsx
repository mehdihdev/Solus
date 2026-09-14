// SOLUSDEV-246 (STORE ST5) — the requirement: typed ("holds 2 kg at 30 cm",
// protocol, voltage) or derived from a CAD assembly (Solus computes the torque
// from the assembly's geometry and masses; parts with no mass are named and
// can be given one). Both end in the same request.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import type { TorqueApi } from '../../lib/api/resources.sourcing'
import { torqueLine, type SpecForm } from './sourcingLogic'
import { useAssemblies } from './useAssemblies'

const INPUT: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 9px',
  fontSize: 12.5,
  fontFamily: 'var(--font-ui)',
  marginTop: 4
}

export type RequirementMode = 'Describe' | 'From CAD'

export interface CadState {
  assemblyId: string
  /** Mass overrides as typed (kg); `massesFrom` turns them into numbers. */
  masses: Record<string, string>
}

export function TorqueCard({
  torque,
  masses,
  onMass
}: {
  torque: TorqueApi
  masses: Record<string, string>
  onMass: (entityId: string, raw: string) => void
}): React.JSX.Element {
  const missing = (torque.parts ?? []).filter((p) => p.mass_kg === null)
  return (
    <div
      data-testid="torque-card"
      style={{ border: '1px solid var(--bd)', borderRadius: 4, padding: 12, marginTop: 12 }}
    >
      <Mono size={9.5}>DERIVED TORQUE</Mono>
      <div style={{ fontSize: 13, marginTop: 6, fontWeight: 600 }}>{torqueLine(torque)}</div>
      <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 11.5, color: 'var(--mut)' }}>
        {torque.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
      {missing.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12 }}>
            No mass in the graph for these parts — give one (kg) to include them, or leave them out:
          </div>
          {missing.map((p) => (
            <label
              key={p.entity_id}
              style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}
            >
              <span style={{ fontSize: 12, minWidth: 140 }}>{p.name}</span>
              <input
                aria-label={`Mass of ${p.name} (kg)`}
                inputMode="decimal"
                value={masses[p.entity_id] ?? ''}
                onChange={(e) => onMass(p.entity_id, e.target.value)}
                style={{ ...INPUT, width: 90, marginTop: 0 }}
              />
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function RequirementStep({
  projectId,
  form,
  onForm,
  mode,
  onMode,
  cad,
  onCad,
  torque,
  busy,
  onDerive
}: RequirementStepProps): React.JSX.Element {
  const assemblies = useAssemblies(projectId, mode === 'From CAD')
  const set = (key: keyof SpecForm) => (value: string) => onForm({ ...form, [key]: value })
  const text = (label: string, key: keyof SpecForm, placeholder: string): React.JSX.Element => (
    <label style={{ display: 'block', marginTop: 10 }}>
      <Mono size={9}>{label}</Mono>
      <input
        aria-label={label}
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => set(key)(e.target.value)}
        style={INPUT}
      />
    </label>
  )
  return (
    <div>
      <Segmented
        options={['Describe', 'From CAD'] as const}
        value={mode}
        onChange={onMode}
        size="sm"
        ariaLabel="Requirement source"
      />
      {mode === 'Describe' ? (
        <div>
          {text('Requirement', 'text', 'holds 2 kg at 30 cm, quiet, must speak CAN')}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10 }}>
            {text('Load (kg)', 'loadKg', '2')}
            {text('Arm (m)', 'armM', '0.30')}
            {text('Protocol', 'protocol', 'CAN')}
            {text('Voltage (V)', 'voltageV', '24')}
          </div>
        </div>
      ) : (
        <div style={{ marginTop: 10 }}>
          <AssemblyPicker assemblies={assemblies} cad={cad} onCad={onCad} />
          <div style={{ marginTop: 10, display: 'flex', gap: 10, alignItems: 'center' }}>
            <Button kind="soft" size="sm" disabled={!cad.assemblyId || busy} onClick={onDerive}>
              {busy ? 'Deriving…' : 'Derive torque from geometry'}
            </Button>
            <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>
              Solus computes it from placements and masses; nothing is guessed.
            </span>
          </div>
          {torque && (
            <TorqueCard
              torque={torque}
              masses={cad.masses}
              onMass={(id, raw) => onCad({ ...cad, masses: { ...cad.masses, [id]: raw } })}
            />
          )}
          {text('Anything else', 'text', 'quiet, must speak CAN, IP54')}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {text('Protocol', 'protocol', 'CAN')}
            {text('Voltage (V)', 'voltageV', '24')}
          </div>
        </div>
      )}
    </div>
  )
}

function AssemblyPicker({
  assemblies,
  cad,
  onCad
}: {
  assemblies: ReturnType<typeof useAssemblies>
  cad: CadState
  onCad: (cad: CadState) => void
}): React.JSX.Element {
  return (
    <label style={{ display: 'block' }}>
      <Mono size={9}>Assembly</Mono>
      <select
        aria-label="Assembly"
        value={cad.assemblyId}
        onChange={(e) => onCad({ assemblyId: e.target.value, masses: {} })}
        style={INPUT}
      >
        <option value="">
          {assemblies === null
            ? 'Loading assemblies…'
            : assemblies.length === 0
              ? 'No CAD assembly in this project yet'
              : 'Pick an assembly'}
        </option>
        {(assemblies ?? []).map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>
    </label>
  )
}

interface RequirementStepProps {
  projectId: string
  form: SpecForm
  onForm: (form: SpecForm) => void
  mode: RequirementMode
  onMode: (mode: RequirementMode) => void
  cad: CadState
  onCad: (cad: CadState) => void
  torque: TorqueApi | null
  busy: boolean
  onDerive: () => void
}
