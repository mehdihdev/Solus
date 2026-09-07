// The Code environment dialog's sections (SOLUSDEV-250 / I3), one component
// each so every one stays small: what the live probe found (interpreter, venv),
// what the graph holds (requirements, conflicts) and what SOL proposes. Every
// unknown is named — "not found", "not probed yet" — never guessed.
import { Mono } from '../../components/ui/Mono'
import type {
  CheckerWarning,
  CodeProbe,
  CodeRequirements,
  EnvironmentProposal,
  ProposedEnvironment,
  ProposedRequirement,
  VenvProbe
} from '../../lib/api/resources.codeenv'
import {
  NOT_FOUND_NOTE,
  NOT_PROBED_NOTE,
  NO_PYTHON_NOTE,
  NO_REQUIREMENTS_TEXT,
  NO_VENV_NOTE,
  SECTION_STAGGER_MS,
  evidencePins,
  plural
} from '../project/codeEnvironment.constants'

const LINE: React.CSSProperties = { fontSize: 12, lineHeight: 1.5 }
const MUTED: React.CSSProperties = { ...LINE, color: 'var(--mut)' }
const MONO: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 11 }

/** A titled region; `index` staggers its entrance after the one before. */
export function Section({
  title,
  index,
  children
}: {
  title: string
  index: number
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <section
      aria-label={title}
      className="code-env-in"
      style={{ marginTop: 16, animationDelay: `${index * SECTION_STAGGER_MS}ms` }}
    >
      <Mono size={9.5} style={{ display: 'block', marginBottom: 6 }}>
        {title}
      </Mono>
      {children}
    </section>
  )
}

/** A monospace chip for a path, a file or a requirement. */
export function Chip({ children }: { children: string }): React.JSX.Element {
  return (
    <span
      style={{
        ...MONO,
        display: 'inline-block',
        padding: '2px 7px',
        borderRadius: 4,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        margin: '0 6px 6px 0',
        maxWidth: '100%',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        verticalAlign: 'top'
      }}
    >
      {children}
    </span>
  )
}

function ChipList({ items }: { items: readonly string[] }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap' }}>
      {items.map((item) => (
        <Chip key={item}>{item}</Chip>
      ))}
    </div>
  )
}

function InterpreterRow({ version, path }: { version: string; path: string }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', ...LINE }}>
      <span style={{ fontWeight: 600, minWidth: 56 }}>{version}</span>
      <span style={{ ...MONO, color: 'var(--mut)' }}>{path}</span>
    </div>
  )
}

function toolPresence(probe: CodeProbe): string[] {
  const uv = probe.uv ? `uv ${probe.uv.version}` : `uv ${NOT_FOUND_NOTE}`
  const conda = probe.conda
    ? `conda · ${plural(probe.conda.envs.length, 'env')}`
    : `conda ${NOT_FOUND_NOTE}`
  return [uv, conda]
}

export function InterpreterSection({ probe }: { probe: CodeProbe | null }): React.JSX.Element {
  if (!probe) return <div style={MUTED}>{NOT_PROBED_NOTE}</div>
  // The default python leads; the other interpreters follow without repeating it.
  const others = probe.interpreters.filter((i) => i.path !== probe.python?.path)
  return (
    <div>
      {probe.python ? (
        <InterpreterRow version={probe.python.version} path={probe.python.path} />
      ) : (
        <div style={MUTED}>{NO_PYTHON_NOTE}</div>
      )}
      {others.map((i) => (
        <InterpreterRow key={i.path} version={i.version} path={i.path} />
      ))}
      <div style={{ ...MUTED, marginTop: 4, display: 'flex', gap: 14 }}>
        {toolPresence(probe).map((text) => (
          <span key={text}>{text}</span>
        ))}
      </div>
    </div>
  )
}

function packagesLine(venv: VenvProbe): string {
  const count = venv.packages.length
  return venv.truncated ? `${plural(count, 'package')} listed, and more` : plural(count, 'package')
}

export function VenvSection({ probe }: { probe: CodeProbe | null }): React.JSX.Element {
  if (!probe) return <div style={MUTED}>{NOT_PROBED_NOTE}</div>
  const venv = probe.venv
  if (!venv) return <div style={MUTED}>{NO_VENV_NOTE}</div>
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', ...LINE }}>
        <span style={MONO}>{venv.path}</span>
        <span style={{ color: 'var(--mut)' }}>Python {venv.python_version}</span>
      </div>
      <div style={{ ...MUTED, margin: '4px 0 6px' }}>{packagesLine(venv)}</div>
      <ChipList items={venv.packages.map((p) => `${p.name} ${p.version}`)} />
    </div>
  )
}

export function RequirementsSection({
  requirements
}: {
  requirements: CodeRequirements
}): React.JSX.Element {
  return (
    <div>
      <div style={{ ...MUTED, marginBottom: 6 }}>{plural(requirements.count, 'requirement')}</div>
      <ChipList items={requirements.files} />
    </div>
  )
}

function ConflictCard({ warning }: { warning: CheckerWarning }): React.JSX.Element {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ ...LINE, color: 'var(--err)' }}>{warning.message}</div>
      {evidencePins(warning.evidence).map((pin) => (
        <div key={`${pin.source_file}:${pin.specifier}`} style={{ ...MONO, color: 'var(--mut)' }}>
          {pin.specifier} · {pin.source_file}
        </div>
      ))}
    </div>
  )
}

export function ConflictsSection({
  conflicts
}: {
  conflicts: readonly CheckerWarning[]
}): React.JSX.Element {
  if (conflicts.length === 0) return <div style={MUTED}>No conflicts found.</div>
  return (
    <div>
      {conflicts.map((warning, i) => (
        <ConflictCard key={`${warning.checker_id}-${i}`} warning={warning} />
      ))}
    </div>
  )
}

function requirementChip(req: ProposedRequirement): string {
  return `${req.name}${req.specifier}`
}

function EnvironmentCard({ environment }: { environment: ProposedEnvironment }): React.JSX.Element {
  return (
    <div
      data-testid={`proposal-${environment.name}`}
      style={{
        border: '1px solid var(--bd)',
        borderRadius: 6,
        padding: '10px 12px',
        marginBottom: 8,
        background: 'var(--sur)'
      }}
    >
      <div style={{ ...LINE, fontWeight: 600, marginBottom: 4 }}>{environment.name}</div>
      <ChipList items={environment.source_files} />
      <div style={{ ...MUTED, margin: '2px 0 6px' }}>
        {plural(environment.requirements.length, 'requirement')}
      </div>
      <ChipList items={environment.requirements.map(requirementChip)} />
    </div>
  )
}

function proposalHeadline(proposal: EnvironmentProposal): string {
  return proposal.split
    ? `Split into ${plural(proposal.environments.length, 'environment')}`
    : 'Single environment'
}

export function ProposalSection({
  proposal,
  requirementCount
}: {
  proposal: EnvironmentProposal | null
  requirementCount: number
}): React.JSX.Element {
  if (requirementCount === 0 || !proposal) return <div style={MUTED}>{NO_REQUIREMENTS_TEXT}</div>
  return (
    <div>
      <div style={{ ...MUTED, marginBottom: 8 }}>{proposalHeadline(proposal)}</div>
      {proposal.environments.map((environment) => (
        <EnvironmentCard key={environment.name} environment={environment} />
      ))}
    </div>
  )
}
