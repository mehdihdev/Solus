// A project's linked repo (SOLUSDEV-317): provider logo + repo name, "+N" for
// more. One component for the project card and the project pane header so the
// two never disagree. The repo is user-controlled text: rendered as text only.
import { integrationLogo } from '../onboarding/integrationLogos'
import type { LinkedRepo } from './useProjectRepos'

export interface RepoLineProps {
  repos: readonly LinkedRepo[]
  /** `md` for the pane header; the card uses the default `sm`. */
  size?: 'sm' | 'md'
}

const SIZES = {
  sm: { logo: 12, text: 11.5 },
  md: { logo: 14, text: 12.5 }
} as const

export function RepoLine({ repos, size = 'sm' }: RepoLineProps): React.JSX.Element | null {
  const first = repos[0]
  if (!first) return null
  const logo = integrationLogo(first.provider)
  const { logo: logoPx, text } = SIZES[size]
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      {logo && (
        <img
          src={logo}
          alt=""
          data-testid={`repo-logo-${first.provider}`}
          style={{ width: logoPx, height: logoPx, objectFit: 'contain', flexShrink: 0 }}
        />
      )}
      <span
        style={{
          fontSize: text,
          color: 'var(--tx)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
      >
        {first.repo}
      </span>
      {repos.length > 1 && (
        <span style={{ fontSize: text - 0.5, color: 'var(--mut)', flexShrink: 0 }}>
          +{repos.length - 1}
        </span>
      )}
    </span>
  )
}
