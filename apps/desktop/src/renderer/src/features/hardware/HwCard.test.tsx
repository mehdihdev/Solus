// SOLUSDEV-326 P3: the card of the Hardware page's slot (spec "The card (HwCard)", CardSheet).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CardKind } from '@solus/shared-types'
import { resultWord } from './cardDecision'
import { HwCard } from './HwCard'
import { card, SAMPLE_CARDS } from './testing/cards'

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'hwCard.css'),
  'utf8'
)
/** The declarations of one CSS rule, by its exact selector. */
function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  expect(start, `no rule ${selector}`).toBeGreaterThanOrEqual(0)
  return css.slice(start, css.indexOf('}', start))
}

/** jsdom lays nothing out: say the body is taller than its two clamped lines. */
function overflowing(): void {
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(80)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(39)
}

afterEach(() => vi.restoreAllMocks())

describe('kinds', () => {
  const KINDS: [CardKind, string | null, string][] = [
    ['offer', null, 'var(--acc)'],
    ['approval', 'APPROVAL · THIS CHANGES THE HARDWARE', 'var(--warn)'],
    ['step', 'YOUR STEP', 'var(--sw)'],
    ['problem', 'PROBLEM', 'var(--err)']
  ]
  it.each(KINDS)('%s has its kicker, its edge and its buttons', (kind, kicker, edge) => {
    render(<HwCard card={card({ kind, title: 'A title', primary: 'Go', secondary: 'Not now' })} />)
    const section = screen.getByRole('region', { name: 'A title' })
    expect(section).toHaveAttribute('data-kind', kind)
    expect(section.querySelector('.hw-card__kicker')?.textContent ?? null).toBe(kicker)
    expect(rule(`.hw-card[data-kind='${kind}'] > .hw-card__edge`)).toContain(edge)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Go', 'Not now'])
  })

  it('an offer titled like an approval is still an offer: the kind alone picks the styling', () => {
    render(<HwCard card={card({ kind: 'offer', title: 'Approve: flash the Nano' })} />)
    const section = screen.getByRole('region', { name: 'Approve: flash the Nano' })
    expect(section).toHaveAttribute('data-kind', 'offer')
    expect(section.querySelector('.hw-card__kicker')).toBeNull()
    expect(section.textContent).not.toContain('THIS CHANGES THE HARDWARE')
  })

  it('draws the frame of the spec: 3px | 1fr | auto, radius 6, at least 132 px', () => {
    const frame = rule('.hw-card')
    expect(frame).toContain('grid-template-columns: 3px minmax(0, 1fr) auto')
    expect(frame).toContain('border-radius: 6px')
    expect(frame).toContain('min-height: 132px')
    expect(frame).toContain('background: var(--sur)')
    expect(frame).toContain('border: 1px solid var(--bd)')
  })

  it('an approval is filled at 10% warn and outlined in warn all round', () => {
    const approval = rule(".hw-card[data-kind='approval']")
    expect(approval).toContain('color-mix(in srgb, var(--warn) 10%, var(--bg))')
    expect(approval).toContain('border-color: var(--warn)')
  })

  it('names no colour of its own', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i)
  })

  it('the primary is a primary button and the secondary a ghost; one button when there is no secondary', () => {
    render(<HwCard card={card({ primary: 'Add to workspace graph', secondary: null })} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0].style.background).toBe('var(--acc)')
  })
})

describe('copy that must fit', () => {
  it('has the 29 sample cards of the spec', () => expect(SAMPLE_CARDS).toHaveLength(29))

  it('their button labels are 24 characters or fewer, but for the one the spec itself overruns', () => {
    const labels = SAMPLE_CARDS.flatMap(({ card: c }) => [c.primary, c.secondary ?? ''])
    expect(labels.filter((label) => label.length > 24)).toEqual(['Use a LeRobot file instead'])
  })

  it('keeps the title on one line and clamps the body to two', () => {
    const title = rule('.hw-card__title')
    expect(title).toContain('white-space: nowrap')
    expect(title).toContain('text-overflow: ellipsis')
    expect(title).toContain('font-size: 13.5px')
    expect(title).toContain('font-weight: 600')
    const body = rule('.hw-card__body')
    expect(body).toContain('max-width: 560px')
    expect(body).toContain('font-size: 12.5px')
    expect(body).toContain('line-height: 1.55')
    expect(body).toContain('opacity: 0.86')
    expect(rule(".hw-card__body[data-expanded='false']")).toContain('-webkit-line-clamp: 2')
  })

  it.each(SAMPLE_CARDS.map((s, i) => [i + 1, s] as const))(
    'sample %i: whole title in one heading, clamped body with "more", every button label in full',
    (_n, { card: c, status }) => {
      overflowing()
      const view = render(<HwCard card={c} status={status} />)
      expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent(c.title)
      const body = view.container.querySelector('.hw-card__body')
      expect(body).toHaveAttribute('data-expanded', 'false')
      expect(body?.textContent).toBe(c.body.replaceAll('`', ''))
      const labels = [c.primary, ...(c.secondary ? [c.secondary] : [])]
      for (const label of labels) {
        expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
      }
      fireEvent.click(screen.getByRole('button', { name: 'more' }))
      expect(body).toHaveAttribute('data-expanded', 'true')
      expect(screen.getByRole('button', { name: 'less' })).toHaveAttribute('aria-expanded', 'true')
      if (status) expect(view.container.querySelector('.hw-card__status')).toHaveTextContent(status)
    }
  )

  it('shows no "more" when the body fits and the card has nothing more to say', () => {
    render(<HwCard card={card()} />)
    expect(screen.queryByRole('button', { name: 'more' })).toBeNull()
  })

  it('"more" reveals card.more even when the body fits', () => {
    render(<HwCard card={card({ more: 'A servo bus carries every motor on one cable.' })} />)
    expect(screen.queryByText(/servo bus carries/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'more' }))
    expect(screen.getByText('A servo bus carries every motor on one cable.')).toBeInTheDocument()
  })
})

describe('model-authored text', () => {
  it('renders backtick spans as code chips', () => {
    const view = render(
      <HwCard card={card({ body: 'Run `ssh-copy-id pi@raspberrypi.local` then `exit`. Done.' })} />
    )
    const chips = [...view.container.querySelectorAll('code.hw-card__code')]
    expect(chips.map((c) => c.textContent)).toEqual(['ssh-copy-id pi@raspberrypi.local', 'exit'])
    const chip = rule('.hw-card__code')
    expect(chip).toContain('font-family: var(--font-mono)')
    expect(chip).toContain('font-size: 11.5px')
    expect(chip).toContain('background: var(--sur2)')
    expect(chip).toContain('border: 1px solid var(--bd)')
  })

  it('leaves a lone backtick as text', () => {
    const view = render(<HwCard card={card({ body: 'A lone ` tick' })} />)
    expect(view.container.querySelector('code')).toBeNull()
    expect(view.container.querySelector('.hw-card__body')?.textContent).toBe('A lone ` tick')
  })

  it('renders HTML-looking text inert, everywhere it prints', () => {
    const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script><b>bold</b>'
    const view = render(
      <HwCard
        card={card({
          title: evil,
          body: `${evil} \`${evil}\``,
          more: evil,
          field: { label: evil, value: evil },
          primary: evil,
          secondary: evil
        })}
        status={evil}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'more' }))
    expect(view.container.querySelector('img, script, b')).toBeNull()
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe(evil)
    expect(view.container.querySelector('code')?.textContent).toBe(evil)
  })
})

describe('field, status and progress', () => {
  it('shows the field as a mono label and a 220 px input prefilled with the value', () => {
    const onFieldChange = vi.fn()
    render(
      <HwCard
        card={card({ field: { label: 'Robot name', value: 'Rover arm' } })}
        onFieldChange={onFieldChange}
      />
    )
    const input = screen.getByLabelText('Robot name')
    expect(input).toHaveValue('Rover arm')
    expect(rule('.hw-card__field input')).toContain('width: 220px')
    expect(rule('.hw-card__field input')).toContain('background: var(--bg)')
    expect(rule('.hw-card__field span')).toContain('font-family: var(--font-mono)')
    fireEvent.change(input, { target: { value: 'Arm B' } })
    expect(onFieldChange).toHaveBeenCalledWith('Arm B')
  })

  it('shows the edited value it is given', () => {
    render(
      <HwCard card={card({ field: { label: 'Robot name', value: 'Rover arm' } })} fieldValue="B" />
    )
    expect(screen.getByLabelText('Robot name')).toHaveValue('B')
  })

  it('draws a status line and a progress bar only when given them', () => {
    const view = render(<HwCard card={card({ kind: 'step' })} />)
    expect(view.container.querySelector('.hw-card__status')).toBeNull()
    expect(screen.queryByRole('progressbar')).toBeNull()
    view.rerender(<HwCard card={card({ kind: 'step' })} status="1 of 6 done" progress={1 / 6} />)
    expect(view.container.querySelector('.hw-card__status')).toHaveTextContent('1 of 6 done')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '17')
    expect(rule('.hw-card__progress > span')).toContain('background: var(--sw)')
  })
})

describe('buttons', () => {
  it('calls back for each button', () => {
    const onPrimary = vi.fn()
    const onSecondary = vi.fn()
    render(<HwCard card={card()} onPrimary={onPrimary} onSecondary={onSecondary} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(onPrimary).toHaveBeenCalledOnce()
    expect(onSecondary).toHaveBeenCalledOnce()
  })

  it('the pressed button shows its result word and the other is disabled', () => {
    render(<HwCard card={card()} pressed={{ button: 'primary', word: 'Added' }} />)
    expect(screen.getByRole('button', { name: 'Added' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Not now' })).toBeDisabled()
  })

  it('cannot be answered with an emptied field', () => {
    render(
      <HwCard card={card({ field: { label: 'Robot name', value: 'Rover arm' } })} fieldValue=" " />
    )
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Not now' })).toBeEnabled()
  })

  it('says a failure where the buttons are', () => {
    render(<HwCard card={card()} error="That did not go through. Try again." />)
    expect(screen.getByRole('alert')).toHaveTextContent('That did not go through. Try again.')
  })

  it('marks itself leaving', () => {
    render(<HwCard card={card({ title: 'T' })} leaving />)
    expect(screen.getByRole('region', { name: 'T' })).toHaveAttribute('data-leaving', 'true')
  })
})

describe('motion', () => {
  it('arrives in 200 ms ease-out with a 4 px drop and leaves in 160 ms ease-in, 6 px up', () => {
    expect(rule('.hw-card')).toContain('animation: hw-card-in 200ms ease-out')
    expect(rule(".hw-card[data-leaving='true']")).toContain(
      'animation: hw-card-out 160ms ease-in forwards'
    )
    expect(css).toMatch(/@keyframes hw-card-in \{\s*from \{[^}]*translateY\(-4px\)/)
    expect(css).toMatch(/@keyframes hw-card-out \{\s*to \{[^}]*translateY\(-6px\)/)
  })

  it('reduced motion is a 120 ms cross-fade only', () => {
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(reduced).toContain('animation: hw-card-fade-in 120ms linear')
    expect(reduced).toContain('animation: hw-card-fade-out 120ms linear forwards')
    expect(css).toMatch(/@keyframes hw-card-fade-in \{\s*from \{\s*opacity: 0;\s*\}\s*\}/)
  })
})

describe('resultWord', () => {
  it.each([
    ['approval', 'Approve', 'primary', 'Approved'],
    ['approval', 'Run the check', 'primary', 'Approved'],
    ['offer', 'Add', 'primary', 'Added'],
    ['offer', 'Add to workspace graph', 'primary', 'Added'],
    ['offer', 'Connect', 'primary', 'Done'],
    ['step', 'Set it to ID 6', 'primary', 'Done'],
    ['offer', 'Not now', 'secondary', 'Not now'],
    ['approval', 'Skip', 'secondary', 'Skip']
  ] as const)('%s "%s" (%s) reads %s', (kind, label, button, word) => {
    const c =
      button === 'primary' ? card({ kind, primary: label }) : card({ kind, secondary: label })
    expect(resultWord(c, button)).toBe(word)
  })
})
