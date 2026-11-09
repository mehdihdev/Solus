// What SOL says on each onboarding step (docs/wireflows/onboarding.md §Steps):
// a mono caption, the headline (the step's heading) and one or two body lines.
// Keyed by step so each step's lines rise in fresh.
import { Mono } from '../../components/ui/Mono'
import type { OnboardingStep } from './onboardingStore'

interface Lines {
  caption: string
  headline: string
  body: readonly string[]
}

const LINES: Readonly<Record<OnboardingStep, Lines>> = {
  0: {
    caption: 'SOL',
    headline: 'Hi — I’m SOL.',
    body: [
      'I connect your code, boards, CAD and the running robot — then catch what breaks between them, before the robot does.',
      'Let’s get you set up. About two minutes.'
    ]
  },
  1: {
    caption: 'SOL · LISTENING',
    headline: 'What are you building?',
    body: [
      'One sentence is plenty. I’ll name your project from it and learn which worlds your robot lives in.'
    ]
  },
  2: {
    caption: 'SOL · VOICE',
    headline: 'How should I talk to you?',
    body: ['Pick one and see me answer the same question that way. Switch any time in Settings.']
  },
  3: {
    caption: 'SOL · ACCESS',
    headline: 'Want me to see what you see?',
    body: [
      'I’m most useful when I can look at the tool you’re stuck in. You decide how much I can do — every switch starts off.'
    ]
  },
  4: {
    caption: 'SOL · SOURCES',
    headline: 'Plug in your tools.',
    body: [
      'Each one becomes a world in your graph. Two is the magic number — cross-domain checks need something to cross.'
    ]
  },
  5: {
    caption: 'SOL · BUILDING',
    headline: 'Building your graph.',
    body: [
      'I’m reading each source and linking the parts that are the same physical thing across tools.'
    ]
  }
}

const DELAYS = ['ob-d2', 'ob-d3'] as const

export function SolLines({ step }: { step: OnboardingStep }): React.JSX.Element {
  const lines = LINES[step]
  return (
    <div key={step} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <span className="ob-rise">
        <Mono size={10} color="var(--acc)">
          {lines.caption}
        </Mono>
      </span>
      <h1
        className="ob-rise ob-d1"
        style={{
          margin: 0,
          fontSize: 34,
          lineHeight: 1.12,
          fontWeight: 600,
          letterSpacing: '-0.025em'
        }}
      >
        {lines.headline}
      </h1>
      {lines.body.map((line, i) => (
        <p
          key={line}
          className={`ob-rise ${DELAYS[i] ?? 'ob-d3'}`}
          style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: 'var(--mut)' }}
        >
          {line}
        </p>
      ))}
    </div>
  )
}
