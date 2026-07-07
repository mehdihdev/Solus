// Guided tour overlay, ported from GuideTour in TestDesign/app/sol.jsx: a
// spotlight ring over the target element, an orbiting orb, and a step card.
// Targets are located by selector and re-measured on an interval so the ring
// follows layout changes; a missing target degrades to a centered card
// (jsdom-safe — never crashes).
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { SolOrb } from '../../components/ui/SolOrb'

export interface TourStep {
  target: string
  text: string
  action: 'click' | null
}

export interface TourState {
  steps: TourStep[]
  idx: number
  advance: () => void
}

const REMEASURE_MS = 300
const CLICK_ADVANCE_MS = 700

/** Center of the target, or of the viewport when the target is missing. */
function anchorPoint(rect: DOMRect | null): { ox: number; oy: number } {
  return {
    ox: rect ? rect.left + rect.width / 2 : window.innerWidth / 2,
    oy: rect ? rect.top + rect.height / 2 : window.innerHeight / 2
  }
}

/** Card placement: below the target when there is room, above otherwise. */
function tipPosition(rect: DOMRect | null, ox: number, oy: number): { left: number; top: number } {
  const tipBelow = oy < window.innerHeight - 180
  const below = rect ? rect.bottom + 18 : oy + 40
  const above = rect ? rect.top - 120 : oy - 130
  return {
    left: Math.min(Math.max(ox - 150, 16), window.innerWidth - 320),
    top: tipBelow ? below : above
  }
}

/** Track the step target's bounding rect, re-measuring on an interval. */
function useTargetRect(target: string | undefined): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null)
  useEffect(() => {
    if (!target) return
    let alive = true
    const find = (): void => {
      const el = document.querySelector(target)
      if (!alive) return
      setRect(el ? el.getBoundingClientRect() : null)
    }
    find()
    const iv = setInterval(find, REMEASURE_MS)
    return () => {
      alive = false
      clearInterval(iv)
    }
  }, [target])
  return rect
}

export function GuideTour({
  tour,
  onEnd
}: {
  tour: TourState
  onEnd: () => void
}): React.JSX.Element | null {
  const step = tour.steps[tour.idx] as TourStep | undefined
  const rect = useTargetRect(step?.target)

  if (!step) return null
  const isLast = tour.idx + 1 >= tour.steps.length
  const finishOrAdvance = (): void => {
    if (isLast) onEnd()
    else tour.advance()
  }
  const doIt = (): void => {
    const el = document.querySelector(step.target)
    if (el instanceof HTMLElement) el.click()
    setTimeout(finishOrAdvance, CLICK_ADVANCE_MS)
  }

  const { ox, oy } = anchorPoint(rect)
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 80, pointerEvents: 'none' }}>
      {rect && <SpotlightRing rect={rect} />}
      <div
        style={{
          position: 'absolute',
          left: ox,
          top: oy,
          transition: 'all 0.7s cubic-bezier(.35,1.1,.3,1)'
        }}
      >
        <div style={{ position: 'absolute', left: -(rect ? rect.width / 2 + 34 : 30), top: -16 }}>
          <SolOrb size={32} pulse />
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          ...tipPosition(rect, ox, oy),
          width: 300,
          pointerEvents: 'auto',
          transition: 'all 0.6s cubic-bezier(.35,1.1,.3,1)'
        }}
      >
        <TourCard
          step={step}
          idx={tour.idx}
          total={tour.steps.length}
          isLast={isLast}
          onEnd={onEnd}
          onNext={finishOrAdvance}
          onDoIt={doIt}
        />
      </div>
    </div>
  )
}

function TourCard({
  step,
  idx,
  total,
  isLast,
  onEnd,
  onNext,
  onDoIt
}: {
  step: TourStep
  idx: number
  total: number
  isLast: boolean
  onEnd: () => void
  onNext: () => void
  onDoIt: () => void
}): React.JSX.Element {
  return (
    <Card
      pad={14}
      style={{
        borderColor: 'color-mix(in srgb, var(--acc) 50%, var(--bd))',
        boxShadow: '0 12px 40px rgba(0,0,0,0.5)'
      }}
    >
      <Mono size={9} color="var(--acc)">
        SOL · STEP {idx + 1} OF {total}
      </Mono>
      <div style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 7 }}>{step.text}</div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
        <Button kind="bare" size="sm" onClick={onEnd}>
          End tour
        </Button>
        {step.action === 'click' ? (
          <Button kind="primary" size="sm" onClick={onDoIt}>
            Do it for me
          </Button>
        ) : (
          <Button kind="primary" size="sm" onClick={onNext}>
            {isLast ? 'Done' : 'Next'}
          </Button>
        )}
      </div>
    </Card>
  )
}

function SpotlightRing({ rect }: { rect: DOMRect }): React.JSX.Element {
  return (
    <div
      style={{
        position: 'absolute',
        left: rect.left - 6,
        top: rect.top - 6,
        width: rect.width + 12,
        height: rect.height + 12,
        border: '1.5px solid var(--acc)',
        borderRadius: 6,
        boxShadow:
          '0 0 0 4000px rgba(0,0,0,0.45), 0 0 18px color-mix(in srgb, var(--acc) 60%, transparent)',
        transition: 'all 0.5s cubic-bezier(.35,1.2,.35,1)'
      }}
    />
  )
}
