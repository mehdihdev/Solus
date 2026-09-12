// A code-section `config` entry rendered as a compact card (SOLUSDEV-252 S5).
// The payload arrives untyped from the API; it is narrowed here, and anything
// that is not a CodeEnvironment renders as one honest line — never invented.
import { useState } from 'react'
import { Mono } from '../../components/ui/Mono'

export type EnvironmentProvenance = 'detected' | 'user' | 'sol'

export interface CodeEnvironment {
  type: string
  name: string
  path: string | null
  interpreter: string | null
  image: string | null
  packages: { name: string; version: string | null }[]
  detected_on: { os: string | null; arch: string | null } | null
  provenance: EnvironmentProvenance
  captured_at: string | null
}

const PROVENANCE_LABEL: Readonly<Record<EnvironmentProvenance, string>> = {
  detected: 'detected',
  user: 'you',
  sol: 'sol'
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null

const optString = (v: unknown): string | null => (typeof v === 'string' ? v : null)

function parsePackages(raw: unknown): CodeEnvironment['packages'] | null {
  if (!Array.isArray(raw)) return null
  const out: CodeEnvironment['packages'] = []
  for (const item of raw) {
    if (!isRecord(item) || typeof item.name !== 'string') return null
    out.push({ name: item.name, version: optString(item.version) })
  }
  return out
}

/** Type guard for the API's CodeEnvironment document; null when it is not one. */
export function parseCodeEnvironment(payload: unknown): CodeEnvironment | null {
  if (!isRecord(payload)) return null
  const { type, name, provenance, detected_on } = payload
  const packages = parsePackages(payload.packages)
  if (typeof type !== 'string' || typeof name !== 'string' || packages === null) return null
  if (provenance !== 'detected' && provenance !== 'user' && provenance !== 'sol') return null
  return {
    type,
    name,
    packages,
    provenance,
    path: optString(payload.path),
    interpreter: optString(payload.interpreter),
    image: optString(payload.image),
    captured_at: optString(payload.captured_at),
    detected_on: isRecord(detected_on)
      ? { os: optString(detected_on.os), arch: optString(detected_on.arch) }
      : null
  }
}

const MONO = { fontFamily: 'var(--font-mono)', fontSize: 10, overflowWrap: 'anywhere' } as const

function formatCaptured(iso: string | null): string | null {
  const at = iso ? new Date(iso) : null
  return at && !Number.isNaN(at.getTime()) ? at.toLocaleString() : null
}

function Captured({ env }: { env: CodeEnvironment }): React.JSX.Element | null {
  const on = [env.detected_on?.os, env.detected_on?.arch].filter(Boolean).join('/')
  const when = formatCaptured(env.captured_at)
  if (!on && !when) return null
  return (
    <Mono size={8} ls="0.05em" style={{ textTransform: 'none' }}>
      {when && <time dateTime={env.captured_at ?? undefined}>{when}</time>}
      {when && on ? ' · ' : ''}
      {on}
    </Mono>
  )
}

function Packages({ packages }: Pick<CodeEnvironment, 'packages'>): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const label = `${packages.length} package${packages.length === 1 ? '' : 's'}`
  if (packages.length === 0) return <Mono size={8}>{label}</Mono>
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? '▾ ' : '▸ '}
        {label}
      </button>
      {open && (
        <ul style={{ ...MONO, margin: '4px 0 0', paddingLeft: 12 }}>
          {packages.map((p) => (
            <li key={p.name}>
              <span>{p.name}</span>
              {p.version && <span style={{ color: 'var(--mut)', marginLeft: 6 }}>{p.version}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CodeEnvironmentCard({ payload }: { payload: unknown }): React.JSX.Element {
  const env = parseCodeEnvironment(payload)
  if (env === null) return <span>environment (unreadable)</span>
  const where = env.image ?? [env.interpreter, env.path].filter(Boolean).join(' · ')
  return (
    <div className="solus-entry-content" style={{ display: 'grid', gap: 4 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <Mono size={8} color="var(--acc)">
          {env.type}
        </Mono>
        <strong>{env.name}</strong>
        <Mono size={8} style={{ marginLeft: 'auto' }}>
          {PROVENANCE_LABEL[env.provenance]}
        </Mono>
      </div>
      {where && <span style={MONO}>{where}</span>}
      <Packages packages={env.packages} />
      <Captured env={env} />
    </div>
  )
}
