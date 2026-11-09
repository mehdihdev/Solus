// SOLUSDEV-323: the compact starter signed-out users meet (replaces the old
// full-window landing). SOL introduces itself, then two doors: create an
// account (which grows into onboarding) or sign in. The orb is the shell's.
import { Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { dcol, type DomainId } from '../../theme/tokens.constants'
import { useAuthStore } from '../../store/authStore'
import { GithubButton } from './GithubButton'

const WORLDS: readonly { label: string; domain: DomainId }[] = [
  { label: 'CODE', domain: 'sw' },
  { label: 'PCB', domain: 'ee' },
  { label: 'CAD', domain: 'me' },
  { label: 'ROBOT', domain: 'rt' }
]

function WorldChain(): React.JSX.Element {
  return (
    <div className="auth-chain ob-rise ob-d3" aria-label="Code, PCB, CAD and robot, linked">
      {WORLDS.map((w, i) => (
        <Fragment key={w.label}>
          {i > 0 && <span className="auth-chain-wire" aria-hidden="true" />}
          <span className="auth-chain-world">
            <span className="auth-chain-dot" style={{ background: dcol(w.domain) }} />
            {w.label}
          </span>
        </Fragment>
      ))}
    </div>
  )
}

export function StarterPage(): React.JSX.Element {
  const navigate = useNavigate()
  const signInWithGitHub = useAuthStore((s) => s.signInWithGitHub)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26, textAlign: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
        <Mono size={10} color="var(--acc)">
          SOL · HELLO
        </Mono>
        <h1
          style={{
            margin: 0,
            fontSize: 26,
            lineHeight: 1.15,
            fontWeight: 600,
            letterSpacing: '-0.02em'
          }}
        >
          Your robot is one system.
          <br />
          <span style={{ color: 'var(--acc)' }}>Your tools aren’t.</span>
        </h1>
        <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.6, color: 'var(--mut)' }}>
          I’m SOL. I connect your code, boards, CAD and the running robot — and catch what breaks
          between them.
        </p>
      </div>
      <WorldChain />
      <div className="ob-rise ob-d4" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Button
          kind="primary"
          size="lg"
          onClick={() => navigate('/signup')}
          style={{ width: '100%' }}
        >
          Create account
        </Button>
        <Button kind="ghost" size="lg" onClick={() => navigate('/login')} style={{ width: '100%' }}>
          Sign in
        </Button>
        <GithubButton label="Continue with GitHub" onAuthorize={signInWithGitHub} />
      </div>
    </div>
  )
}
