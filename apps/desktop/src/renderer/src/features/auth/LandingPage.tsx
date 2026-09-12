// Landing / marketing entry, ported from LandingPage in TestDesign/app/auth.jsx.
import { Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Wordmark } from '../../components/ui/Wordmark'
import { Icons } from '../../components/ui/icons.constants'
import { AuthChrome } from './AuthLayout'
import { dcol, type DomainId } from '../../theme/tokens.constants'

const CHAIN: { label: string; domain: DomainId }[] = [
  { label: 'motor_driver.c', domain: 'sw' },
  { label: 'M3_PWM', domain: 'ee' },
  { label: 'DRV8316C · U4', domain: 'ee' },
  { label: 'knee gearbox 9:1', domain: 'me' },
  { label: 'τ3 torque', domain: 'rt' }
]

export function LandingPage(): React.JSX.Element {
  return (
    <AuthChrome>
      <LandingNav />
      <LandingHero />
      <LandingFooter />
    </AuthChrome>
  )
}

function LandingNav(): React.JSX.Element {
  const navigate = useNavigate()
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '20px 48px'
      }}
    >
      <Wordmark />
      <div style={{ display: 'flex', gap: 28, fontSize: 13.5, color: 'var(--mut)' }}>
        <span style={{ cursor: 'pointer' }}>Product</span>
        <span style={{ cursor: 'pointer' }}>Docs</span>
        <span style={{ cursor: 'pointer' }}>Pricing</span>
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span
          onClick={() => navigate('/login')}
          style={{ fontSize: 13.5, color: 'var(--mut)', cursor: 'pointer' }}
        >
          Sign in
        </span>
        <Button kind="primary" size="sm" onClick={() => navigate('/signup')}>
          Get started
        </Button>
      </div>
    </div>
  )
}

function LandingHero(): React.JSX.Element {
  const navigate = useNavigate()
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '48px 96px 24px'
      }}
    >
      <Mono color="var(--acc)" size={11} style={{ letterSpacing: '0.16em', marginBottom: 18 }}>
        CODE · PCB · CAD · HARDWARE — ONE GRAPH
      </Mono>
      <h1
        style={{
          margin: 0,
          fontWeight: 600,
          fontSize: 'clamp(40px, 5vw, 64px)',
          lineHeight: 1.04,
          letterSpacing: '-0.025em',
          maxWidth: 880
        }}
      >
        Your robot is one system.
        <br />
        <span style={{ color: 'var(--acc)' }}>Your tools aren&apos;t.</span>
      </h1>
      <p
        style={{ fontSize: 17, lineHeight: 1.6, color: 'var(--mut)', maxWidth: 560, marginTop: 22 }}
      >
        Solus connects firmware, schematics, CAD, and live telemetry into one workspace graph — and
        catches the integration bugs that only exist between them, before they break the robot.
      </p>
      <div style={{ display: 'flex', gap: 12, marginTop: 32 }}>
        <Button kind="primary" size="lg" onClick={() => navigate('/signup')}>
          Create account
        </Button>
        <Button kind="ghost" size="lg" onClick={() => navigate('/signup')}>
          See it catch a bug <Icons.arrowR size={14} />
        </Button>
      </div>
      <DomainChain />
      <Mono size={10.5} style={{ marginTop: 14, letterSpacing: '0.06em', textTransform: 'none' }}>
        one broken assumption, traced across four domains — in 90 ms
      </Mono>
    </div>
  )
}

function DomainChain(): React.JSX.Element {
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', marginTop: 60, flexWrap: 'wrap', rowGap: 10 }}
    >
      {CHAIN.map((c, i) => (
        <Fragment key={c.label}>
          {i > 0 && <div style={{ width: 34, height: 1, background: 'var(--bd)' }} />}
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--tx)',
              background: 'var(--sur)',
              border: `1px solid color-mix(in srgb, ${dcol(c.domain)} 38%, transparent)`,
              borderRadius: 3,
              padding: '6px 11px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              whiteSpace: 'nowrap'
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 99,
                background: dcol(c.domain),
                display: 'inline-block'
              }}
            />
            {c.label}
          </span>
        </Fragment>
      ))}
    </div>
  )
}

function LandingFooter(): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '18px 48px',
        borderTop: '1px solid var(--bd)'
      }}
    >
      <Mono size={10}>WORKS WITH GITHUB · KICAD · ONSHAPE · ROS 2</Mono>
      <Mono size={10}>SOC 2 · SELF-HOST AVAILABLE</Mono>
    </div>
  )
}
