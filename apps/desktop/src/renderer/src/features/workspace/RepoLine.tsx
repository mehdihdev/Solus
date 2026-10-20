// A project's linked repo (SOLUSDEV-317): provider logo + repo name, "+N" for
// more. One component for the project card and the project pane header so the
// two never disagree. The repo is user-controlled text: rendered as text only.
import './home.css'
import { integrationLogo, logoClass } from '../onboarding/integrationLogos'
import { repoUrl, type LinkedRepo } from './useProjectRepos'

export interface RepoLineProps {
  repos: readonly LinkedRepo[]
  /** `md` for the pane header; the card uses the default `sm`. */
  size?: 'sm' | 'md'
  /** Make the repo a link to its page on the code host (opens in the browser). */
  linked?: boolean
}

const SIZES = {
  sm: { logo: 12, text: 11.5 },
  md: { logo: 14, text: 12.5 }
} as const

export function RepoLine({
  repos,
  size = 'sm',
  linked = false
}: RepoLineProps): React.JSX.Element | null {
  const first = repos[0]
  if (!first) return null
  const logo = integrationLogo(first.provider)
  const { logo: logoPx, text } = SIZES[size]
  const href = linked ? repoUrl(first) : null
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      {logo && (
        <img
          src={logo}
          alt=""
          className={logoClass(first.provider)}
          data-testid={`repo-logo-${first.provider}`}
          style={{ width: logoPx, height: logoPx, objectFit: 'contain', flexShrink: 0 }}
        />
      )}
      <RepoName name={first.repo} href={href} fontSize={text} />
      {repos.length > 1 && (
        <span style={{ fontSize: text - 0.5, color: 'var(--mut)', flexShrink: 0 }}>
          +{repos.length - 1}
        </span>
      )}
    </span>
  )
}

/** The repo's name — a link to its page (the main process opens it in the
 *  system browser) when there is one, else text. */
function RepoName({
  name,
  href,
  fontSize
}: {
  name: string
  href: string | null
  fontSize: number
}): React.JSX.Element {
  const style: React.CSSProperties = {
    fontSize,
    color: 'var(--tx)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap'
  }
  if (!href) return <span style={style}>{name}</span>
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${name} on the web`}
      className="repo-link"
      style={style}
    >
      {name}
    </a>
  )
}
