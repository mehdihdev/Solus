// Onboarding step 1 — Meet (SOLUSDEV-323, docs/wireflows/onboarding.md §1):
// what SOL does, in three plain cards, then "Let's set up".
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { EyeGlyph, GlyphTile, GraphGlyph, PointerGlyph } from './onboardingIcons'

const CARDS = [
  {
    icon: <GraphGlyph />,
    title: 'Reads your whole robot',
    body: 'One graph across GitHub, KiCad, Onshape and ROS — so a pin change in the schematic shows up next to the firmware that uses it.'
  },
  {
    icon: <EyeGlyph />,
    title: 'Sees what you’re stuck on',
    body: 'Double-tap Ctrl in any app, or circle something, and ask. Only if you let me — and I forget the picture after.'
  },
  {
    icon: <PointerGlyph />,
    title: 'Catches what breaks between worlds',
    body: 'A moved pin, an address clash, a part that no longer fits — I flag cross-domain conflicts before they reach the robot.'
  }
] as const

const DELAYS = ['ob-d3', 'ob-d4', 'ob-d5'] as const

export function MeetStep({ onNext }: { onNext: () => void }): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 14,
        flex: 1
      }}
    >
      <span className="ob-rise ob-d2">
        <Mono size={9.5}>WHAT I DO FOR YOU</Mono>
      </span>
      {CARDS.map((card, i) => (
        <Card key={card.title} pad={0} className={`ob-rise ${DELAYS[i]}`}>
          <div style={{ padding: '18px 20px', display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <GlyphTile>{card.icon}</GlyphTile>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{card.title}</div>
              <div style={{ fontSize: 13, color: 'var(--mut)', marginTop: 4, lineHeight: 1.55 }}>
                {card.body}
              </div>
            </div>
          </div>
        </Card>
      ))}
      <div
        className="ob-rise ob-d5"
        style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}
      >
        <Button kind="primary" size="lg" onClick={onNext}>
          Let’s set up <Icons.arrowR size={14} />
        </Button>
      </div>
    </div>
  )
}
