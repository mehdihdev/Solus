// SOLUSDEV-321 P2-T7 — one finding in the Live Bench Findings pane. Headline, evidence, causes
// and the narration (`explanation`, and `detail` as lines) are UNTRUSTED text (findings.md §1):
// they render as React text nodes only, never as markup. The evidence shown is the top-level
// keys (latest-wins, M71) — never the `items` history.
import { useState } from 'react'
import type { Finding } from '../../../lib/api/findings'
import { relativeTime } from '../../../lib/relativeTime'
import { useSettingsStore } from '../../../store/settingsStore'
import {
  dismissBenchFinding,
  explainFinding,
  fileFinding,
  findingCodeSite,
  openFindingCodeSite,
  proposeFindingFix,
  resolveBenchFinding,
  type CodeSite
} from './findingActions'

interface FindingCardProps {
  projectId: string
  finding: Finding
  /** A finding a signal marker opened starts expanded. */
  defaultOpen?: boolean
  /** The finding changed status here (dismissed/resolved): re-read the pane. */
  onChanged: () => void
}

export function FindingCard({
  projectId,
  finding,
  defaultOpen = false,
  onChanged
}: FindingCardProps): React.JSX.Element {
  const [open, setOpen] = useState(defaultOpen)
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  return (
    <article className="bench-finding">
      <button
        type="button"
        className="bench-text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <strong>{finding.headline}</strong>
      </button>
      <p>
        {finding.severity} · ×{finding.count} · last seen{' '}
        <time dateTime={finding.last_seen} title={finding.last_seen}>
          {relativeTime(finding.last_seen)}
        </time>
      </p>
      {guide && finding.explanation && <p>{finding.explanation}</p>}
      {open && <FindingDetail finding={finding} guide={guide} />}
      <FindingActionBar
        projectId={projectId}
        finding={finding}
        site={findingCodeSite(finding)}
        onChanged={onChanged}
      />
    </article>
  )
}

function FindingDetail({
  finding,
  guide
}: {
  finding: Finding
  guide: boolean
}): React.JSX.Element {
  const site = siteText(finding.evidence.code_site)
  const also = textList(finding.evidence.also)
  return (
    <>
      {!guide && finding.explanation && <p>{finding.explanation}</p>}
      {(finding.detail ?? '')
        .split('\n')
        .filter((line) => line.trim())
        .map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      <EvidenceList evidence={finding.evidence} />
      <CauseList finding={finding} />
      {site && (
        <p>
          Code: <span>{site}</span>
        </p>
      )}
      {also.length > 0 && <p>Also seen: {also.join(', ')}</p>}
    </>
  )
}

/** Keys shown elsewhere on the card, or ids that mean nothing to a person. */
const NOT_EVIDENCE = new Set(['items', 'causes', 'code_site', 'also', 'robot_id', 'session_id'])
const MAX_ROWS = 40

type Scalar = string | number | boolean | null

function EvidenceList({ evidence }: { evidence: Record<string, unknown> }): React.JSX.Element {
  const rows = Object.entries(evidence)
    .filter((entry): entry is [string, Scalar] => !NOT_EVIDENCE.has(entry[0]) && isScalar(entry[1]))
    .slice(0, MAX_ROWS)
  return (
    <ul aria-label="Evidence">
      {rows.map(([key, value]) => (
        <li key={key}>
          <span>{key.replaceAll('_', ' ')}</span>: <span>{shown(value)}</span>
        </li>
      ))}
    </ul>
  )
}

interface Cause {
  kind: string
  for: string[]
  against: string[]
}

function CauseList({ finding }: { finding: Finding }): React.JSX.Element | null {
  const ranked = finding.causes_ranked ?? []
  const causes = Array.isArray(finding.evidence.causes)
    ? finding.evidence.causes.flatMap(toCause)
    : []
  if (!causes.length) return null
  const rank = (cause: Cause): number => {
    const index = ranked.indexOf(cause.kind)
    return index < 0 ? ranked.length : index
  }
  return (
    <>
      <p>
        <strong>Likely causes</strong>
        {ranked.length > 0 && ' (most likely first)'}
      </p>
      <ul aria-label="Likely causes">
        {[...causes]
          .sort((a, b) => rank(a) - rank(b))
          .map((cause) => (
            <li key={cause.kind}>
              <strong>{cause.kind.replaceAll('_', ' ')}</strong>
              {cause.for.length > 0 && ` — for: ${cause.for.join('; ')}`}
              {cause.against.length > 0 && ` — against: ${cause.against.join('; ')}`}
            </li>
          ))}
      </ul>
    </>
  )
}

function toCause(value: unknown): Cause[] {
  if (typeof value !== 'object' || value === null) return []
  const { kind, for: pro, against } = value as Record<string, unknown>
  return typeof kind === 'string' && kind
    ? [{ kind, for: textList(pro), against: textList(against) }]
    : []
}

function textList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function isScalar(value: unknown): value is Scalar {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

function shown(value: Scalar): string {
  if (value === null) return '—'
  return typeof value === 'number' ? String(Number(value.toPrecision(6))) : String(value)
}

/** `path:line` of the evidence's code site, for display; null without a path. */
function siteText(value: unknown): string | null {
  if (typeof value !== 'object' || value === null) return null
  const { path, line } = value as Record<string, unknown>
  if (typeof path !== 'string' || !path) return null
  return Number.isSafeInteger(line) ? `${path}:${line as number}` : path
}

interface ActionSpec {
  key: string
  label: string
  busyLabel: string
  run: () => Promise<string>
}

const asked = (sent: boolean): string =>
  sent ? 'SOL answered in the SOL window.' : 'SOL could not take this now — see the SOL window.'

function actionSpecs(
  projectId: string,
  finding: Finding,
  site: CodeSite | null,
  onChanged: () => void
): ActionSpec[] {
  const explain = async (): Promise<string> => asked(await explainFinding(projectId, finding))
  const fix = async (): Promise<string> => asked(await proposeFindingFix(projectId, finding))
  const launch = async (code: CodeSite): Promise<string> => {
    const result = await openFindingCodeSite(projectId, code)
    return result.launched ? 'Opened on this machine.' : (result.reason ?? 'The tool did not open.')
  }
  const file = async (): Promise<string> => {
    await fileFinding(projectId, finding)
    return 'Filed to .solus › Error logging.'
  }
  const dismiss = async (): Promise<string> => {
    await dismissBenchFinding(projectId, finding)
    onChanged()
    return 'Dismissed for 24 hours.'
  }
  return [
    { key: 'explain', label: 'Explain more', busyLabel: 'Asking SOL…', run: explain },
    { key: 'fix', label: 'Propose a fix', busyLabel: 'Asking SOL…', run: fix },
    ...(site
      ? [{ key: 'open', label: 'Open the tool', busyLabel: 'Opening…', run: () => launch(site) }]
      : []),
    { key: 'file', label: 'File', busyLabel: 'Filing…', run: file },
    { key: 'dismiss', label: 'Dismiss', busyLabel: 'Dismissing…', run: dismiss }
  ]
}

function FindingActionBar({
  projectId,
  finding,
  site,
  onChanged
}: {
  projectId: string
  finding: Finding
  site: CodeSite | null
  onChanged: () => void
}): React.JSX.Element {
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set())
  const [status, setStatus] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  async function run(key: string, action: () => Promise<string>): Promise<void> {
    setBusy((previous) => new Set(previous).add(key))
    try {
      setStatus(await action())
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The action failed.')
    } finally {
      setBusy((previous) => new Set([...previous].filter((item) => item !== key)))
    }
  }
  const resolve = (note: string, fixRef: string | null): void =>
    void run('resolve', async () => {
      await resolveBenchFinding(projectId, finding, note, fixRef)
      onChanged()
      return 'Resolved and filed to .solus › Error logging.'
    })
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
      {actionSpecs(projectId, finding, site, onChanged).map((spec) => (
        <button
          key={spec.key}
          type="button"
          className="bench-text-button"
          disabled={busy.has(spec.key)}
          onClick={() => void run(spec.key, spec.run)}
        >
          {busy.has(spec.key) ? spec.busyLabel : spec.label}
        </button>
      ))}
      <button
        type="button"
        className="bench-text-button"
        aria-expanded={resolving}
        onClick={() => setResolving(!resolving)}
      >
        Resolve with note
      </button>
      {resolving && <ResolveForm site={site} busy={busy.has('resolve')} onResolve={resolve} />}
      {status && <p role="status">{status}</p>}
    </div>
  )
}

/** The route's own bound on a resolution note (docs/api/findings.md §3). */
const MAX_NOTE = 4000

function ResolveForm({
  site,
  busy,
  onResolve
}: {
  site: CodeSite | null
  busy: boolean
  onResolve: (note: string, fixRef: string | null) => void
}): React.JSX.Element {
  const [note, setNote] = useState('')
  const [fixed, setFixed] = useState(false)
  return (
    <form
      style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}
      onSubmit={(event) => {
        event.preventDefault()
        onResolve(note, fixed && site ? site.entity_id : null)
      }}
    >
      <textarea
        aria-label="Resolution note"
        maxLength={MAX_NOTE}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      {site && (
        <label>
          <input
            type="checkbox"
            checked={fixed}
            onChange={(event) => setFixed(event.target.checked)}
          />{' '}
          Fixed in {siteText({ path: site.path, line: site.line }) ?? 'the commanding code'}
        </label>
      )}
      <button type="submit" disabled={busy || !note.trim()}>
        Resolve
      </button>
    </form>
  )
}
