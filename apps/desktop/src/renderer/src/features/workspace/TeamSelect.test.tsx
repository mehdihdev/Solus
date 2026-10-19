// The team title as the team switcher (SOLUSDEV-317): plain text with one
// team; with more, a button whose menu lists every team, the active one
// checked; Escape closes it; re-picking the active team does nothing.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamSelect } from './TeamSelect'
import type { TeamSummary } from '../../lib/api/resources'

const STRIDER: TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}
const PERSONAL: TeamSummary = { ...STRIDER, team_id: 't-me', name: 'Maya', is_personal: true }

describe('TeamSelect', () => {
  it('is plain text with a single team', () => {
    render(<TeamSelect teams={[STRIDER]} team={STRIDER} onSwitch={vi.fn()} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('lists every team, checks the active one and marks personal', async () => {
    render(<TeamSelect teams={[PERSONAL, STRIDER]} team={STRIDER} onSwitch={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: 'Strider, switch team' })
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitemradio', { name: /strider/i })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    expect(screen.getByRole('menuitemradio', { name: /maya/i })).toHaveTextContent('personal')
  })

  it('switches to another team, and re-picking the active one does nothing', async () => {
    const onSwitch = vi.fn()
    render(<TeamSelect teams={[PERSONAL, STRIDER]} team={STRIDER} onSwitch={onSwitch} />)
    await userEvent.click(screen.getByRole('button', { name: /switch team/i }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /strider/i }))
    expect(onSwitch).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /switch team/i }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /maya/i }))
    expect(onSwitch).toHaveBeenCalledWith('t-me')
  })

  it('closes on Escape and returns focus to the title', async () => {
    render(<TeamSelect teams={[PERSONAL, STRIDER]} team={STRIDER} onSwitch={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /switch team/i })
    await userEvent.click(trigger)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger).toHaveFocus()
  })
})
