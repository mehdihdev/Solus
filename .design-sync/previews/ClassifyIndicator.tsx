import { Card, ClassifyIndicator, Mono } from '@solus/desktop'

const noop = (): void => {}

const NO_OVERRIDE = { complexity: null, type: null, thinkHarder: false }

const COMPLEXITIES = [
  { value: 'trivial', viable: true, reason: null, cost_tier: 'low' },
  { value: 'standard', viable: true, reason: null, cost_tier: 'standard' },
  { value: 'hard', viable: true, reason: null, cost_tier: 'premium' }
]

const TYPES = [
  { value: 'general', viable: true, reason: null, cost_tier: 'standard' },
  { value: 'code', viable: true, reason: null, cost_tier: 'standard' },
  { value: 'visual_log', viable: true, reason: null, cost_tier: 'standard' },
  {
    value: 'long_context',
    viable: false,
    reason: 'Too many tokens for this tier (340K > 200K)',
    cost_tier: 'premium'
  }
]

const PREVIEW = {
  complexity: 'standard',
  type: 'code',
  reasoner: { name: 'sol-reasoner-1', effort: 'standard' },
  cost_tier: 'standard',
  source: { complexity: 'estimator', type: 'context' },
  tokens_estimate: 4820,
  viable: true,
  reason: null,
  escalated: false,
  options: { complexities: COMPLEXITIES, types: TYPES }
}

function Composer({ children, caption }: { children: React.ReactNode; caption: string }) {
  return (
    <Card style={{ width: 380 }}>
      <Mono>{caption}</Mono>
      <div
        style={{
          marginTop: 10,
          padding: '9px 10px',
          border: '1px solid var(--bd)',
          borderRadius: 3,
          background: 'var(--sur2)',
          color: 'var(--mut)',
          fontSize: 11.5
        }}
      >
        Why does the I²C bus drop out when the arm motor spins up?
      </div>
      {children}
    </Card>
  )
}

export function IdleRouting() {
  return (
    <Composer caption="ASK SOL — NOTHING CLASSIFIED YET">
      <ClassifyIndicator
        preview={null}
        override={NO_OVERRIDE}
        onOverride={noop}
        onReset={noop}
      />
    </Composer>
  )
}

export function Classified() {
  return (
    <Composer caption="ASK SOL — PRE-FLIGHT ROUTING">
      <ClassifyIndicator
        preview={PREVIEW}
        override={NO_OVERRIDE}
        onOverride={noop}
        onReset={noop}
      />
    </Composer>
  )
}

export function Overridden() {
  return (
    <Composer caption="ASK SOL — TIER RAISED FOR THIS MESSAGE">
      <ClassifyIndicator
        preview={{
          ...PREVIEW,
          complexity: 'hard',
          reasoner: { name: 'sol-reasoner-1', effort: 'deep' },
          cost_tier: 'premium',
          escalated: true
        }}
        override={{ complexity: 'hard', type: null, thinkHarder: true }}
        onOverride={noop}
        onReset={noop}
      />
    </Composer>
  )
}

export function NotViable() {
  return (
    <Composer caption="ASK SOL — TIER CANNOT TAKE THIS MESSAGE">
      <ClassifyIndicator
        preview={{
          ...PREVIEW,
          type: 'long_context',
          viable: false,
          reason: 'Too many tokens for this tier (340K > 200K)'
        }}
        override={{ complexity: null, type: 'long_context', thinkHarder: false }}
        onOverride={noop}
        onReset={noop}
      />
    </Composer>
  )
}
