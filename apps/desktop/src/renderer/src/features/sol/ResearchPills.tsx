// SOLUSDEV-321 P1-T5: the sources of a turn's web research, as pills under the reply. A URL is
// untrusted text from the open web (CLAUDE.md §7), so a pill shows its title and URL as plain
// TEXT — never an anchor, never markup — and:
// - "Open" is enabled only for an https URL and goes through `window.open`: the main window and
//   the SOL window both route that to the system browser over https alone (externalOpenHandler),
//   and it is never a navigation, so the renderer itself cannot leave its bundle;
// - "File" saves the title and URL as a plain-text `.solus/documentation/datasheets` entry — only
//   on the person's click, never automatically.
import { useState } from 'react'
import { addSolusEntry } from '../../lib/api/resources'
import type { ResearchSource, ResearchSources } from './researchSources'
import './ResearchPills.css'

export interface ResearchPillsProps {
  /** The turn's sources (absent or empty renders nothing). */
  readonly research: ResearchSources | undefined
  readonly projectId: string
}

const OPEN_FEATURES = 'noopener,noreferrer'

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return ''
  }
}

/** What the pill is called: the page title, else its host, else the address itself. */
const labelOf = (source: ResearchSource): string => source.title || hostOf(source.url) || source.url

type Filing = 'idle' | 'busy' | 'filed'
const FILE_LABEL: Record<Filing, string> = { idle: 'File', busy: 'Filing…', filed: 'Filed' }

function Pill({
  source,
  projectId
}: {
  source: ResearchSource
  projectId: string
}): React.JSX.Element {
  const [filing, setFiling] = useState<Filing>('idle')
  const [error, setError] = useState<string | null>(null)
  const label = labelOf(source)

  const file = async (): Promise<void> => {
    setFiling('busy')
    setError(null)
    try {
      await addSolusEntry(projectId, 'documentation', {
        kind: 'text',
        text: `${label}\n${source.url}`,
        subsection: 'datasheets'
      })
      setFiling('filed')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'That didn’t go through.')
      setFiling('idle')
    }
  }

  return (
    <li className="research-pill">
      <span className="research-pill__label">{label}</span>
      {label !== source.url && <span className="research-pill__url">{source.url}</span>}
      {source.fetched && <span className="research-pill__tag">read</span>}
      <button
        type="button"
        className="research-pill__action"
        aria-label={`Open ${label}`}
        disabled={!source.url.startsWith('https://')}
        onClick={() => window.open(source.url, '_blank', OPEN_FEATURES)}
      >
        Open
      </button>
      <button
        type="button"
        className="research-pill__action"
        aria-label={`File ${label}`}
        disabled={filing !== 'idle'}
        onClick={() => void file()}
      >
        {FILE_LABEL[filing]}
      </button>
      {error && (
        <span role="alert" className="research-pill__error">
          {error}
        </span>
      )}
    </li>
  )
}

export function ResearchPills({
  research,
  projectId
}: ResearchPillsProps): React.JSX.Element | null {
  if (!research || research.sources.length === 0) return null
  return (
    <section className="research-pills" aria-label="Web sources">
      <div className="research-pills__head">
        <span>Web sources</span>
        {research.cached && <span className="research-pill__tag">cached</span>}
      </div>
      <ul className="research-pills__list">
        {research.sources.map((source) => (
          <Pill key={source.url} source={source} projectId={projectId} />
        ))}
      </ul>
    </section>
  )
}
