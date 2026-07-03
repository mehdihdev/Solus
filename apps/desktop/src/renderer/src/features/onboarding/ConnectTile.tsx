// Connect tile, ported from ConnectTile in TestDesign/app/onboarding.jsx. The
// GitHub tile additionally drives the real connector: a busy state can carry a
// live `label`, a repo picker (`repos`), or an `error` phase, and the done
// state shows a real `result` string (SOLUSDEV-103).
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { GithubRepo } from '../../lib/api/resources'
import type { Integration } from './integrations.constants'
import type { ConnectionState } from './onboardingStore'

interface ConnectTileProps {
  integration: Integration
  state?: ConnectionState
  onConnect: () => void
  /** Resolve the repo picker (GitHub real flow). */
  onChooseRepo?: (repo: GithubRepo) => void
  /** Retry after an error (GitHub real flow). */
  onRetry?: () => void
}

function TileIndicator({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state)
    return <span style={{ color: 'var(--acc)', fontSize: 12, fontWeight: 500 }}>Connect</span>
  if (state.phase === 'busy') return <Spinner />
  if (state.phase === 'error')
    return <span style={{ color: 'var(--err)', fontSize: 12, fontWeight: 500 }}>Retry</span>
  return (
    <span style={{ color: 'var(--ok)' }}>
      <Icons.check size={15} />
    </span>
  )
}

const MONO = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const

function busyLabel(
  integration: Integration,
  state: Extract<ConnectionState, { phase: 'busy' }>
): string {
  return state.label ?? integration.steps[state.stepIdx] ?? integration.steps[0]
}

function TileFooter({
  integration,
  state
}: {
  integration: Integration
  state?: ConnectionState
}): React.JSX.Element {
  if (!state) return <span style={{ fontSize: 11, color: 'var(--mut)' }}>Not connected</span>
  if (state.phase === 'busy') {
    return <span style={{ ...MONO, color: 'var(--acc)' }}>{busyLabel(integration, state)}</span>
  }
  if (state.phase === 'error') {
    return <span style={{ ...MONO, color: 'var(--err)' }}>{state.error}</span>
  }
  return <span style={{ ...MONO, color: 'var(--ok)' }}>{state.result ?? integration.result}</span>
}

function RepoPicker({
  repos,
  onChooseRepo
}: {
  repos: GithubRepo[]
  onChooseRepo?: (repo: GithubRepo) => void
}): React.JSX.Element {
  return (
    <select
      aria-label="Choose a repository"
      defaultValue=""
      onChange={(e) => {
        const repo = repos.find((r) => r.full_name === e.target.value)
        if (repo) onChooseRepo?.(repo)
      }}
      onClick={(e) => e.stopPropagation()}
      style={{
        marginTop: 8,
        width: '100%',
        background: 'var(--sur)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '7px 9px',
        fontSize: 11.5,
        fontFamily: 'var(--font-mono)',
        outline: 'none'
      }}
    >
      <option value="" disabled>
        Select a repository…
      </option>
      {repos.map((r) => (
        <option key={r.full_name} value={r.full_name}>
          {r.full_name}
        </option>
      ))}
    </select>
  )
}

function borderFor(state?: ConnectionState): string {
  if (state?.phase === 'done') return 'color-mix(in srgb, var(--ok) 45%, var(--bd))'
  if (state?.phase === 'error') return 'color-mix(in srgb, var(--err) 45%, var(--bd))'
  if (state?.phase === 'busy') return 'var(--acc)'
  return 'var(--bd)'
}

export function ConnectTile({
  integration,
  state,
  onConnect,
  onChooseRepo,
  onRetry
}: ConnectTileProps): React.JSX.Element {
  const clickable = !state || state.phase === 'error'
  const handleClick = !state ? onConnect : state.phase === 'error' ? onRetry : undefined
  const repos = state?.phase === 'busy' ? state.repos : undefined
  return (
    <Card
      pad={0}
      onClick={clickable ? handleClick : undefined}
      style={{
        cursor: clickable ? 'pointer' : 'default',
        overflow: 'hidden',
        borderColor: borderFor(state),
        transition: 'border-color 0.2s'
      }}
    >
      <div style={{ padding: '16px 16px 14px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <span
          style={{
            width: 38,
            height: 38,
            borderRadius: 3,
            background: 'var(--sur2)',
            border: '1px solid var(--bd)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--tx)',
            flexShrink: 0
          }}
        >
          {integration.mark}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{integration.name}</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{integration.kind}</div>
        </div>
        <TileIndicator state={state} />
      </div>
      <div
        style={{
          borderTop: '1px solid var(--bd)',
          padding: '9px 16px',
          minHeight: 16,
          background: 'var(--bg)'
        }}
      >
        <TileFooter integration={integration} state={state} />
        {repos && repos.length > 0 && <RepoPicker repos={repos} onChooseRepo={onChooseRepo} />}
      </div>
    </Card>
  )
}
